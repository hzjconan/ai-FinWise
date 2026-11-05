"""L09：同一 PNG 管线的单进程 / 多进程对照，不执行模型训练。

仓库根目录运行：
    backend/.venv/bin/python -m backend.scratch.robot_pipeline_parallel

也可在 backend/ 中运行 .venv/bin/python -m scratch.robot_pipeline_parallel。
"""
from __future__ import annotations

import argparse
import gc
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

import torch
from torch.utils.data import DataLoader

from .robot_pipeline_baseline import RobotWindowDataset, make_fixture, timed_collate


def _skip_tracker_finalizer(self):
    """采用上游修复，避免解释器结束时阻塞等待资源跟踪进程。"""
    pass


def _apply_pinned_macos_compat():
    # 仅兼容仓库固定环境，不修改 site-packages 或其他 Python / PyTorch 版本。
    # 上游同类修复：https://github.com/pytorch/pytorch/commit/3a7ff82
    # 问题：https://github.com/pytorch/pytorch/issues/153050
    if (sys.platform == "darwin" and sys.version_info[:2] == (3, 12)
            and torch.__version__.split("+")[0] == "2.2.2"):
        from multiprocessing.resource_tracker import ResourceTracker
        if hasattr(ResourceTracker, "__del__"):
            ResourceTracker.__del__ = _skip_tracker_finalizer
            return True
    return False


# spawn 子进程也会 import 此模块，因此父进程和加载进程都应用相同兼容。
MACOS_COMPAT_ACTIVE = _apply_pinned_macos_compat()


def init_worker(worker_id):
    # 加载进程数与每进程内的 PyTorch 算子线程数分开控制。
    torch.set_num_threads(1)


def collate_with_pid(samples):
    # 顶层函数可被 spawn 序列化；组批发生在哪个进程，用 PID 留下证据。
    batch = timed_collate(samples)
    batch["loader_pid"] = os.getpid()
    return batch


def build_loader(dataset, *, batch_size=8, num_workers=0, prefetch_factor=2,
                 persistent_workers=True):
    if batch_size < 1 or num_workers < 0 or prefetch_factor < 1:
        raise ValueError("batch_size/prefetch_factor 必须为正，num_workers 不能为负")
    options = dict(batch_size=batch_size, num_workers=num_workers, shuffle=False,
                   drop_last=False, collate_fn=collate_with_pid)
    if num_workers > 0:
        options.update(prefetch_factor=prefetch_factor,
                       persistent_workers=persistent_workers,
                       multiprocessing_context="spawn", worker_init_fn=init_worker)
    # num_workers=0 不传多进程专属参数，避免 PyTorch 参数校验报错。
    return DataLoader(dataset, **options)


def run_epoch(loader):
    """总耗时是主进程经过的时间；阶段累计量是各加载进程的工作时间之和。"""
    stages = {name: 0.0 for name in ("read", "decode", "preprocess", "collate")}
    sample_ids, batch_sizes, targets, pids = [], [], [], set()
    first_batch_ms = None
    start = time.perf_counter()  # 包含 iter(loader) 的启动 / 重置和等待首批。
    for batch in loader:
        if first_batch_ms is None:
            first_batch_ms = (time.perf_counter() - start) * 1000
        expected = torch.stack((batch["episode_id"], batch["anchor_frame"]), dim=1).float()
        if not torch.equal(batch["action"], expected):
            raise ValueError("观测元信息与合成动作目标不匹配")
        sample_ids.extend(batch["sample_id"])
        batch_sizes.append(len(batch["sample_id"]))
        targets.extend(batch["action"].tolist())
        pids.add(batch["loader_pid"])
        for name in ("read", "decode", "preprocess"):
            stages[name] += batch["timing_ms"][name].sum().item()
        stages["collate"] += batch["collate_ms"]
    elapsed = time.perf_counter() - start
    expected_ids = [record["sample_id"] for record in loader.dataset.records]
    if sample_ids != expected_ids:
        raise ValueError("样本次序、覆盖或数量与固定顺序清单不一致")
    return {"sample_ids": sample_ids, "targets": targets, "batch_sizes": batch_sizes,
            "loader_pids": sorted(pids), "samples": len(sample_ids),
            "first_batch_ms": first_batch_ms, "epoch_ms": elapsed * 1000,
            "samples_per_second": len(sample_ids) / elapsed,
            "worker_stage_sum_ms": stages}


def benchmark_setting(dataset, *, num_workers, persistent_workers, epochs=3,
                      batch_size=8, prefetch_factor=2):
    if epochs < 2:
        raise ValueError("至少两轮才能区分首轮和后续轮次")
    loader = build_loader(dataset, num_workers=num_workers, batch_size=batch_size,
                          persistent_workers=persistent_workers,
                          prefetch_factor=prefetch_factor)
    try:
        # 必须复用同一个 loader，persistent_workers 才能体现跨轮次复用。
        rounds = [run_epoch(loader) for _ in range(epochs)]
    finally:
        # DataLoader/iterator 销毁后终止其 worker；先完成此设置，再跑下一设置。
        del loader
        gc.collect()
    return {"num_workers": num_workers,
            "persistent_workers": persistent_workers if num_workers else False,
            "epochs": rounds,
            "later_epoch_median_ms": statistics.median(r["epoch_ms"] for r in rounds[1:])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--prefetch-factor", type=int, default=2)
    parser.add_argument("--samples-per-episode", type=int, default=16)
    args = parser.parse_args()
    if (args.epochs < 2 or args.batch_size < 1 or args.prefetch_factor < 1
            or args.samples_per_episode < 1):
        parser.error("epochs 至少为 2；其他参数必须为正")
    torch.set_num_threads(1)
    print(f"PyTorch {torch.__version__} | CPU | spawn | 每进程 PyTorch threads=1", flush=True)
    if MACOS_COMPAT_ACTIVE:
        print("已启用固定 macOS/Python 3.12/PyTorch 2.2.2 的退出兼容处理。", flush=True)
    print("同一合成 PNG 数据；无训练/视频解码；文件缓存及运行次序会影响结果。", flush=True)
    print("首轮包含启动；不保留 worker 时每轮也包含退出开销。后续中位数不等于生产稳态。", flush=True)
    print("保留 worker 的最后统一退出发生在各轮计时之外；每轮不是完整进程生命周期计时。", flush=True)
    with tempfile.TemporaryDirectory(prefix="l09-parallel-") as folder:
        manifest = make_fixture(Path(folder), samples_per_episode=args.samples_per_episode)
        dataset = RobotWindowDataset(manifest)
        print(f"训练样本={len(dataset)}，batch_size={args.batch_size}，prefetch_factor={args.prefetch_factor}",
              flush=True)
        for workers, persistent in [(0, False), (2, False), (2, True), (4, True)]:
            result = benchmark_setting(dataset, num_workers=workers, persistent_workers=persistent,
                                       epochs=args.epochs, batch_size=args.batch_size,
                                       prefetch_factor=args.prefetch_factor)
            rounds = result["epochs"]
            elapsed = ", ".join(f"{r['epoch_ms']:.2f}" for r in rounds)
            print(f"workers={workers} persistent={result['persistent_workers']} | "
                  f"各轮总 ms=[{elapsed}] | 首轮首批={rounds[0]['first_batch_ms']:.2f} ms | "
                  f"后续中位数={result['later_epoch_median_ms']:.2f} ms", flush=True)
            print(f"  各轮加载进程 PID={[r['loader_pids'] for r in rounds]}", flush=True)
    print("各 worker 的阶段时间之和不等于总耗时；所有轮次均检查样本覆盖与动作配对。")


if __name__ == "__main__":
    main()

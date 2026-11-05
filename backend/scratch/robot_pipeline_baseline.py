"""L09 CPU 数据管线基线：真实 PNG 读取/解码，不执行视频解码或训练。

    backend/.venv/bin/python backend/scratch/robot_pipeline_baseline.py

数据只在临时目录中生成，退出后清理；生成耗时不计入加载吞吐。
"""
from __future__ import annotations

import argparse
import io
import json
import tempfile
import time
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from torch.utils.data import DataLoader, Dataset, default_collate


def make_fixture(root: Path, *, episodes: int = 4, samples_per_episode: int = 16,
                 image_size: int = 96) -> Path:
    """先按 episode 切分，再为每个 episode 建立三帧窗口。

    动作是便于检查配对关系的合成标记，不是实际机器人控制指令。
    """
    if episodes < 2 or samples_per_episode < 1 or image_size < 1:
        raise ValueError("需要至少两个 episode，样本数和图像尺寸必须为正")
    root.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(42)
    records = []
    for episode in range(episodes):
        folder = root / f"episode-{episode}"
        folder.mkdir()
        # 每个窗口三帧，相邻窗口复用两帧；最后一个 episode 留作验证。
        for frame in range(samples_per_episode + 2):
            pixels = rng.integers(0, 256, (image_size, image_size, 3), dtype=np.uint8)
            Image.fromarray(pixels).save(folder / f"{frame:04d}.png")
        for anchor in range(2, samples_per_episode + 2):
            records.append({
                "sample_id": f"{episode}:{anchor}",
                "episode_id": episode,
                "anchor_frame": anchor,
                "split": "val" if episode == episodes - 1 else "train",
                "frame_paths": [f"episode-{episode}/{i:04d}.png"
                                for i in range(anchor - 2, anchor + 1)],
                "action": [float(episode), float(anchor)],
            })
    manifest = root / "manifest.json"
    manifest.write_text(json.dumps(records), encoding="utf-8")
    return manifest


class RobotWindowDataset(Dataset):
    """一个索引 = 一个自包含窗口，返回输入、目标和分段耗时。"""

    def __init__(self, manifest: Path, *, split: str = "train", output_size: int = 112):
        if split not in {"train", "val"} or output_size < 1:
            raise ValueError("split 必须为 train/val，output_size 必须为正")
        self.root = manifest.parent
        self.records = [r for r in json.loads(manifest.read_text(encoding="utf-8"))
                        if r["split"] == split]
        if not self.records:
            raise ValueError("所选 split 不能没有样本")
        self.output_size = output_size

    def __len__(self):
        return len(self.records)

    def __getitem__(self, index):
        record = self.records[index]
        start = time.perf_counter()
        encoded = [(self.root / name).read_bytes() for name in record["frame_paths"]]
        after_read = time.perf_counter()

        frames = []
        for payload in encoded:
            with Image.open(io.BytesIO(payload)) as image:
                image.load()  # Pillow 延迟解码；这里明确在计时范围内完成。
                frames.append(image.convert("RGB"))
        after_decode = time.perf_counter()

        arrays = [np.array(frame.resize((self.output_size, self.output_size),
                                       Image.Resampling.BILINEAR), copy=True)
                  for frame in frames]
        # [帧, 高, 宽, 通道] -> [帧, 通道, 高, 宽]，像素从 uint8 转为 [0, 1]。
        images = torch.from_numpy(np.stack(arrays)).permute(0, 3, 1, 2).float().div_(255)
        action = torch.tensor(record["action"], dtype=torch.float32)
        after_preprocess = time.perf_counter()
        return {
            "images": images,
            "action": action,
            "sample_id": record["sample_id"],
            "episode_id": record["episode_id"],
            "anchor_frame": record["anchor_frame"],
            "timing_ms": {
                "read": (after_read - start) * 1000,
                "decode": (after_decode - after_read) * 1000,
                "preprocess": (after_preprocess - after_decode) * 1000,
            },
        }


def timed_collate(samples):
    """复用 PyTorch 的默认组批逻辑，只增加计时，不改变样本配对。"""
    start = time.perf_counter()
    batch = default_collate(samples)
    batch["collate_ms"] = (time.perf_counter() - start) * 1000
    return batch


def measure(dataset: RobotWindowDataset, *, batch_size: int = 8) -> dict:
    """固定单进程、无 shuffle / 丢尾批，避免先混入并行因素。"""
    if batch_size < 1:
        raise ValueError("batch_size 必须为正")
    loader = DataLoader(dataset, batch_size=batch_size, num_workers=0,
                        shuffle=False, drop_last=False, collate_fn=timed_collate)
    stages = {name: 0.0 for name in ("read", "decode", "preprocess", "collate")}
    sample_ids, batch_sizes = [], []
    start = time.perf_counter()
    for batch in loader:
        batch_sizes.append(len(batch["sample_id"]))
        sample_ids.extend(batch["sample_id"])
        for name in ("read", "decode", "preprocess"):
            stages[name] += batch["timing_ms"][name].sum().item()
        stages["collate"] += batch["collate_ms"]
    elapsed = time.perf_counter() - start
    return {"samples": len(sample_ids), "batches": len(batch_sizes),
            "batch_sizes": batch_sizes, "sample_ids": sample_ids,
            "loader_ms": elapsed * 1000,
            "samples_per_second": len(sample_ids) / elapsed,
            "stages_ms": stages}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=8)
    args = parser.parse_args()
    if args.batch_size < 1:
        parser.error("--batch-size 必须为正")
    torch.set_num_threads(1)
    with tempfile.TemporaryDirectory(prefix="l09-pipeline-") as folder:
        manifest = make_fixture(Path(folder))
        dataset = RobotWindowDataset(manifest)
        result = measure(dataset, batch_size=args.batch_size)
    print(f"PyTorch {torch.__version__} | CPU | num_workers=0 | CPU threads=1")
    print("合成 PNG 窗口，无视频解码/设备传输/模型计算；数据生成不计时。")
    print("刚生成的数据可能命中 OS 文件缓存，本次不是磁盘冷读基准。")
    print(f"train samples={result['samples']} | batch sizes={result['batch_sizes']}")
    for name, elapsed_ms in result["stages_ms"].items():
        print(f"{name:>10}: {elapsed_ms:8.2f} ms（全轮累计）")
    print(f"loader 总时间: {result['loader_ms']:.2f} ms（含迭代及统计开销）")
    print(f"吞吐: {result['samples_per_second']:.2f} samples/s")


if __name__ == "__main__":
    main()

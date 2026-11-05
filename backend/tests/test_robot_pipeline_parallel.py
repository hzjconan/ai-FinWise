"""验证真实 spawn 加载的内容、次序和进程复用，不断言加速比例。"""
import os
from pathlib import Path
import subprocess
import sys

import pytest
import torch

from scratch.robot_pipeline_baseline import RobotWindowDataset, make_fixture
from scratch.robot_pipeline_parallel import benchmark_setting, build_loader, run_epoch


@pytest.fixture
def dataset(tmp_path):
    manifest = make_fixture(tmp_path, samples_per_episode=3, image_size=8)
    return RobotWindowDataset(manifest, output_size=6)


def test_spawn_preserves_images_targets_order_and_tail(dataset):
    serial = build_loader(dataset, batch_size=4)
    parallel = build_loader(dataset, batch_size=4, num_workers=2, persistent_workers=False)
    expected = list(serial)
    actual = list(parallel)
    assert [len(b["sample_id"]) for b in actual] == [4, 4, 1]
    for left, right in zip(expected, actual, strict=True):
        assert left["sample_id"] == right["sample_id"]
        assert torch.equal(left["images"], right["images"])
        assert torch.equal(left["action"], right["action"])
        assert left["loader_pid"] == os.getpid()
        assert right["loader_pid"] != os.getpid()


@pytest.mark.parametrize("persistent", [False, True])
def test_worker_lifecycle_and_coverage_across_epochs(dataset, persistent):
    result = benchmark_setting(dataset, num_workers=2, persistent_workers=persistent,
                               epochs=2, batch_size=4)
    first, second = result["epochs"]
    assert first["sample_ids"] == second["sample_ids"]
    assert first["targets"] == second["targets"]
    assert first["batch_sizes"] == second["batch_sizes"] == [4, 4, 1]
    assert len(first["loader_pids"]) == len(second["loader_pids"]) == 2
    if persistent:
        assert first["loader_pids"] == second["loader_pids"]
    else:
        assert set(first["loader_pids"]).isdisjoint(second["loader_pids"])


def test_zero_workers_uses_main_process_and_ignores_multiprocess_options(dataset):
    loader = build_loader(dataset, num_workers=0, persistent_workers=True)
    assert loader.prefetch_factor is None
    assert loader.persistent_workers is False
    assert run_epoch(loader)["loader_pids"] == [os.getpid()]


def test_pairing_error_is_not_treated_as_a_successful_benchmark(dataset):
    dataset.records[0]["action"] = [999.0, 999.0]
    with pytest.raises(ValueError, match="不匹配"):
        run_epoch(build_loader(dataset))


@pytest.mark.parametrize("options", [{"num_workers": -1}, {"batch_size": 0},
                                     {"prefetch_factor": 0}])
def test_invalid_loader_arguments(dataset, options):
    with pytest.raises(ValueError):
        build_loader(dataset, **options)


def test_single_epoch_cannot_claim_to_measure_reuse(dataset):
    with pytest.raises(ValueError, match="至少两轮"):
        benchmark_setting(dataset, num_workers=0, persistent_workers=False, epochs=1)


def test_cli_completes_and_exits_after_real_spawn_workers():
    # 检测“打印完结果却卡在解释器退出”的回归；不是加速比例断言。
    completed = subprocess.run(
        [sys.executable, "-m", "scratch.robot_pipeline_parallel", "--epochs", "2",
         "--samples-per-episode", "3"],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    assert "workers=4 persistent=True" in completed.stdout
    assert "所有轮次均检查样本覆盖与动作配对" in completed.stdout

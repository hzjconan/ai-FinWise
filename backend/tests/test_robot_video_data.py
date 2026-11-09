"""L13：真实视频、episode 切分、无未来帧输入和动作时间对齐。"""
import json
from pathlib import Path
import subprocess
import sys

import pytest
import torch
from torch.utils.data import DataLoader

from scratch.robot_video_data import VideoActionDataset, make_fixture


@pytest.fixture
def manifest(tmp_path):
    return make_fixture(tmp_path, episodes=8)


def test_episode_splits_and_action_coverage(manifest):
    train = VideoActionDataset(manifest)
    val = VideoActionDataset(manifest, split="val")
    assert len(train) == len(val) == 20
    assert set(train.videos).isdisjoint(val.videos)
    assert set(train.videos) == {f"episode-{i:03d}" for i in range(4)}
    assert set(val.videos) == {f"episode-{i:03d}" for i in range(4, 8)}
    assert {row["action_dx"] for row in train.records} == {-2.0, -1.0, 1.0, 2.0}
    assert {row["action_dx"] for row in val.records} == {-2.0, -1.0, 1.0, 2.0}


def test_real_decoded_motion_matches_next_action_and_window_timing(manifest):
    dataset = VideoActionDataset(manifest)
    for sample in dataset:
        assert sample["images"].shape == (3, 3, 32, 32)
        assert sample["images"].dtype == torch.float32
        centers = []
        for frame in sample["images"]:
            bright = torch.nonzero(frame[0] > 0.5)
            assert len(bright) == 16
            centers.append(bright[:, 1].float().mean().item())
        assert centers[1] - centers[0] == sample["action"].item()
        assert centers[2] - centers[1] == sample["action"].item()
        anchor = sample["anchor_frame"]
        assert sample["frame_indices"].tolist() == [anchor - 2, anchor - 1, anchor]
        assert sample["timestamps_s"].tolist() == [(anchor - 2) / 8, (anchor - 1) / 8, anchor / 8]
        assert sample["action_interval_s"].tolist() == [anchor / 8, (anchor + 1) / 8]
        current_pixels = torch.nonzero(sample["images"][-1, 0] > 0.5)
        expected_xy = current_pixels.min(dim=0).values.flip(0).float()
        assert torch.equal(sample["state_xy"], expected_xy)
        assert torch.allclose(sample["state"], expected_xy / 31)
        assert sample["state_time_s"].item() == sample["timestamps_s"][-1].item()
    assert {row["anchor_frame"] for row in dataset.records} == {2, 3, 4, 5, 6}


def test_batch_shapes_and_sample_mutation_cannot_poison_cache(manifest):
    dataset = VideoActionDataset(manifest)
    before = dataset[0]["images"].clone()
    dataset[0]["images"].zero_()
    assert torch.equal(dataset[0]["images"], before)
    batch = next(iter(DataLoader(dataset, batch_size=8, num_workers=0)))
    assert batch["images"].shape == (8, 3, 3, 32, 32)
    assert batch["action"].shape == (8, 1)
    assert batch["state"].shape == (8, 2)
    assert batch["state"].dtype == torch.float32
    assert torch.all((batch["state"] >= 0) & (batch["state"] <= 1))


def test_future_state_is_not_part_of_current_input(manifest):
    before = VideoActionDataset(manifest)[0]
    payload = json.loads(manifest.read_text())
    payload["episodes"][0]["positions_xy"][3] = [0, 0]
    manifest.write_text(json.dumps(payload))
    after = VideoActionDataset(manifest)[0]
    assert torch.equal(before["images"], after["images"])
    assert torch.equal(before["state"], after["state"])
    assert torch.equal(before["action"], after["action"])


def test_unsynchronized_sensor_time_is_rejected(manifest):
    payload = json.loads(manifest.read_text())
    payload["episodes"][0]["state_timestamps_s"][2] += 0.01
    manifest.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="模拟状态时间戳"):
        VideoActionDataset(manifest)


@pytest.mark.parametrize("positions", [[], [[float("nan"), 0]] * 8])
def test_missing_or_invalid_sensor_positions_are_rejected(manifest, positions):
    payload = json.loads(manifest.read_text())
    payload["episodes"][0]["positions_xy"] = positions
    manifest.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="模拟位置"):
        VideoActionDataset(manifest)


def test_old_manifest_does_not_silently_claim_sensor_support(manifest):
    payload = json.loads(manifest.read_text())
    payload["schema_version"] = 1
    manifest.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="schema_version=2"):
        VideoActionDataset(manifest)


def test_missing_action_is_rejected(manifest):
    payload = json.loads(manifest.read_text())
    payload["episodes"][0]["actions_dx"].pop()
    manifest.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="不一致"):
        VideoActionDataset(manifest)


def test_non_increasing_timestamps_are_rejected(manifest):
    payload = json.loads(manifest.read_text())
    payload["episodes"][0]["timestamps_s"][1] = 0.0
    manifest.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="严格递增"):
        VideoActionDataset(manifest)


def test_rerun_does_not_overwrite_data(manifest):
    original = manifest.read_bytes()
    with pytest.raises(FileExistsError):
        make_fixture(manifest.parent, episodes=8)
    assert manifest.read_bytes() == original


@pytest.mark.parametrize("episodes", [4, 9])
def test_invalid_episode_count_fails_before_creating_files(tmp_path, episodes):
    with pytest.raises(ValueError):
        make_fixture(tmp_path, episodes=episodes)
    assert list(tmp_path.iterdir()) == []


def test_cli_reads_real_videos_and_reports_both_splits(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "scratch.robot_video_data", "--output-dir", str(tmp_path)],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "train: episodes=12, windows=60" in result.stdout
    assert "val: episodes=4, windows=20" in result.stdout
    assert "state_time_s=0.25 batch_state=[8, 2]" in result.stdout
    assert "尚未创建模型或更新参数" in result.stdout

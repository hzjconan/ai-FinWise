"""L09 教学管线：验证窗口、切分和组批正确性，不断言机器性能。"""
from pathlib import Path

import pytest
import torch

from scratch.robot_pipeline_baseline import (
    RobotWindowDataset, make_fixture, measure, timed_collate,
)


@pytest.fixture
def manifest(tmp_path):
    return make_fixture(tmp_path, episodes=4, samples_per_episode=3, image_size=8)


def test_splits_have_disjoint_episodes_and_no_shared_frame_files(manifest):
    train = RobotWindowDataset(manifest)
    val = RobotWindowDataset(manifest, split="val")
    assert len(train) == 9
    assert len(val) == 3
    assert {r["episode_id"] for r in train.records} == {0, 1, 2}
    assert {r["episode_id"] for r in val.records} == {3}
    train_files = {p for r in train.records for p in r["frame_paths"]}
    val_files = {p for r in val.records for p in r["frame_paths"]}
    assert train_files.isdisjoint(val_files)


def test_window_keeps_temporal_order_and_matching_target(manifest):
    dataset = RobotWindowDataset(manifest, output_size=6)
    sample = dataset[4]  # episode 1，锚点帧 3。
    assert sample["sample_id"] == "1:3"
    assert sample["images"].shape == (3, 3, 6, 6)
    assert sample["images"].dtype == torch.float32
    assert 0 <= sample["images"].min() <= sample["images"].max() <= 1
    assert sample["action"].tolist() == [1.0, 3.0]
    assert [int(Path(p).stem) for p in dataset.records[4]["frame_paths"]] == [1, 2, 3]


def test_collate_preserves_pairs_even_when_samples_are_reordered(manifest):
    dataset = RobotWindowDataset(manifest, output_size=6)
    batch = timed_collate([dataset[8], dataset[0]])
    assert batch["images"].shape == (2, 3, 3, 6, 6)
    assert batch["sample_id"] == ["2:4", "0:2"]
    assert batch["action"].tolist() == [[2.0, 4.0], [0.0, 2.0]]


def test_measure_keeps_tail_batch_and_every_sample_once(manifest):
    dataset = RobotWindowDataset(manifest, output_size=6)
    result = measure(dataset, batch_size=4)
    assert result["samples"] == 9
    assert result["batches"] == 3
    assert result["batch_sizes"] == [4, 4, 1]
    assert result["sample_ids"] == [r["sample_id"] for r in dataset.records]
    assert len(set(result["sample_ids"])) == 9
    assert set(result["stages_ms"]) == {"read", "decode", "preprocess", "collate"}


def test_missing_frame_is_reported_instead_of_silently_dropping_sample(manifest):
    dataset = RobotWindowDataset(manifest)
    (manifest.parent / dataset.records[0]["frame_paths"][0]).unlink()
    with pytest.raises(FileNotFoundError):
        dataset[0]


@pytest.mark.parametrize("batch_size", [0, -1])
def test_invalid_batch_size_is_rejected(manifest, batch_size):
    with pytest.raises(ValueError, match="batch_size"):
        measure(RobotWindowDataset(manifest), batch_size=batch_size)


def test_invalid_dataset_arguments_are_rejected(manifest):
    with pytest.raises(ValueError, match="split"):
        RobotWindowDataset(manifest, split="unknown")
    with pytest.raises(ValueError, match="output_size"):
        RobotWindowDataset(manifest, output_size=0)

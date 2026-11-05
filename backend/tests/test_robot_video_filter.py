"""L12：真实 FFV1 编解码、漏检反例、保护规则和安全重跑。"""
import json
from pathlib import Path
import subprocess
import sys

import imageio_ffmpeg
import numpy as np
import pytest

from scratch.robot_video_filter import analyze, decide, make_fixture, motion_summary


def test_darkening_does_not_overflow_uint8():
    white = np.full((4, 4, 3), 255, dtype=np.uint8)
    black = np.zeros_like(white)
    assert motion_summary([white, black]) == (255.0, 2)


def test_small_local_change_is_diluted_by_global_mean():
    before = np.zeros((100, 100, 3), dtype=np.uint8)
    after = before.copy()
    after[49:51, 49:51] = 255
    score, count = motion_summary([before, after])
    assert count == 2
    assert score == pytest.approx(0.102)
    assert decide(score, 1.0)["motion_only_keep"] is False
    assert decide(score, 1.0, ["contact"])["event_guard_keep"] is True
    assert decide(score, 1.0, ["unrecognized"])["event_guard_keep"] is False


@pytest.mark.parametrize("frames", [[], [np.zeros((2, 2, 3), dtype=np.uint8)]])
def test_too_few_frames_fail_instead_of_classifying_as_idle(frames):
    with pytest.raises(ValueError, match="至少两帧"):
        motion_summary(frames)


def test_inconsistent_frame_shape_is_rejected():
    with pytest.raises(ValueError, match="尺寸"):
        motion_summary([np.zeros((2, 2, 3), dtype=np.uint8),
                        np.zeros((4, 4, 3), dtype=np.uint8)])


@pytest.mark.parametrize("threshold", [-1.0, float("nan"), float("inf")])
def test_invalid_threshold_is_rejected(threshold):
    with pytest.raises(ValueError, match="阈值"):
        decide(0.0, threshold)


def test_real_video_fixture_and_full_clip_selection(tmp_path):
    manifest = make_fixture(tmp_path)
    original_bytes = {item["file"]: (tmp_path / item["file"]).read_bytes()
                      for item in manifest["clips"]}
    report = analyze(tmp_path, manifest)
    rows = {row["clip_id"]: row for row in report["clips"]}
    assert {row["frames"] for row in rows.values()} == {12}
    assert {row["fps"] for row in rows.values()} == {6.0}
    assert rows["idle"]["max_mean_change"] == 0.0
    assert rows["moving"]["motion_only_keep"] is True
    assert rows["subtle"]["max_mean_change"] == pytest.approx(0.102)
    assert rows["subtle"]["motion_only_keep"] is False
    assert rows["subtle"]["event_guard_keep"] is True
    assert rows["idle"]["event_guard_keep"] is False
    assert report["motion_only_selected_bytes"] == rows["moving"]["bytes"]
    assert report["event_guard_selected_bytes"] == (rows["moving"]["bytes"]
                                                    + rows["subtle"]["bytes"])
    for name, data in original_bytes.items():
        assert (tmp_path / name).read_bytes() == data

    # 检查实际解码后的短暂区域，没有被编码 / 解码本身抹掉。
    reader = imageio_ffmpeg.read_frames(str(tmp_path / "subtle.mkv"), pix_fmt="rgb24")
    try:
        next(reader)
        frames = [np.frombuffer(data, dtype=np.uint8).reshape(100, 100, 3)
                  for data in reader]
    finally:
        reader.close()
    assert np.count_nonzero(np.any(frames[5] != 0, axis=2)) == 0
    assert np.count_nonzero(np.any(frames[6] != 0, axis=2)) == 4
    assert np.all(frames[6][49:51, 49:51] == 255)
    assert np.count_nonzero(np.any(frames[8] != 0, axis=2)) == 0

    with pytest.raises(FileExistsError):
        make_fixture(tmp_path)
    assert (tmp_path / "subtle.mkv").read_bytes() == original_bytes["subtle.mkv"]


def test_cli_writes_report_and_exits(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "scratch.robot_video_filter", "--output-dir", str(tmp_path)],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads((tmp_path / "report.json").read_text())
    assert len(report["clips"]) == 3
    assert "模拟元数据" in result.stdout

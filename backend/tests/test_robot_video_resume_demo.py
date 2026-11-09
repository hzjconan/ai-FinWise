"""L13：三个真实独立进程验证连续训练、完整续训、优化器状态消融。"""
import json
from pathlib import Path
import subprocess
import sys

from scratch.robot_video_data import make_fixture


def test_cross_process_resume_matches_and_reset_adam_diverges(tmp_path):
    manifest = make_fixture(tmp_path / "data", episodes=8)
    output = tmp_path / "comparison"
    reports = {}
    for mode in ("prepare", "resume", "without-adam"):
        completed = subprocess.run(
            [sys.executable, "-m", "scratch.robot_video_resume_demo", "--manifest", str(manifest),
             "--output-dir", str(output), "--mode", mode],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=45,
        )
        assert completed.returncode == 0, completed.stderr
        reports[mode] = json.loads(completed.stdout)
        assert (output / f"{mode}.json").exists()
    assert reports["prepare"]["reference_global_step"] == 30
    assert reports["prepare"]["interrupted_global_step"] == 15
    full = reports["resume"]
    reset = reports["without-adam"]
    assert full["initial_weights_equal"] is reset["initial_weights_equal"] is True
    assert full["global_step"] == reset["global_step"] == 30
    assert full["optimizer_steps"] == [30.0]
    assert reset["optimizer_steps"] == [15.0]
    assert full["final_weights_equal_reference"] is True
    assert full["optimizer_equal_reference"] is True
    assert full["continuation_history_equal_reference"] is True
    assert all(full["rng_equal_reference"].values())
    assert full["maximum_parameter_difference"] == 0.0
    assert reset["final_weights_equal_reference"] is False
    assert reset["maximum_parameter_difference"] > 0
    assert all(reset["rng_equal_reference"].values())
    assert (output / "resumed-final.pt").exists()

    before = (output / "prepare.json").read_bytes()
    repeated = subprocess.run(
        [sys.executable, "-m", "scratch.robot_video_resume_demo", "--manifest", str(manifest),
         "--output-dir", str(output), "--mode", "prepare"],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30,
    )
    assert repeated.returncode != 0
    assert (output / "prepare.json").read_bytes() == before

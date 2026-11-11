"""L14：验证单位换算、采集与上传边界；不访问网络或真实计费服务。"""
import copy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scratch.robot_cost_model import (
    checkpoint_overhead, compare_costs, daily_video_volume, estimate_scenario, load_scenario, main,
    required_upload_mbps, storage_estimate, training_compute_cost,
)


BASELINE = {"robots": 100, "cameras_per_robot": 2, "bitrate_mbps": 4,
            "recording_hours": 8, "upload_fraction": 0.25}


def test_l10_fleet_capture_and_upload_are_distinct():
    result = daily_video_volume(**BASELINE)
    assert result["captured_gb_per_day"] == pytest.approx(2880)
    assert result["uploaded_gb_per_day"] == pytest.approx(720)


def test_single_camera_full_upload_by_default():
    result = daily_video_volume(robots=1, cameras_per_robot=1, bitrate_mbps=4, recording_hours=8)
    assert result["captured_gb_per_day"] == pytest.approx(14.4)
    assert result["uploaded_gb_per_day"] == pytest.approx(14.4)


def test_fractional_recording_duration():
    result = daily_video_volume(robots=1, cameras_per_robot=1, bitrate_mbps=4, recording_hours=0.5)
    assert result["captured_gb_per_day"] == pytest.approx(0.9)


@pytest.mark.parametrize("field", ["robots", "cameras_per_robot", "bitrate_mbps", "recording_hours"])
def test_no_video_production_has_zero_volume(field):
    result = daily_video_volume(**{**BASELINE, field: 0})
    assert result == {"captured_gb_per_day": 0.0, "uploaded_gb_per_day": 0.0}


def test_filtering_all_upload_does_not_erase_captured_volume():
    result = daily_video_volume(**{**BASELINE, "upload_fraction": 0})
    assert result["captured_gb_per_day"] == pytest.approx(2880)
    assert result["uploaded_gb_per_day"] == 0


@pytest.mark.parametrize("changes", [
    {"robots": -1}, {"robots": 1.5}, {"robots": True},
    {"cameras_per_robot": -1}, {"bitrate_mbps": float("inf")},
    {"recording_hours": float("nan")}, {"recording_hours": 25},
    {"upload_fraction": -0.1}, {"upload_fraction": 25},
])
def test_invalid_units_or_ranges_are_rejected(changes):
    with pytest.raises(ValueError):
        daily_video_volume(**{**BASELINE, **changes})


def test_overflow_is_not_reported_as_infinite_capacity():
    with pytest.raises(ValueError, match="超出"):
        daily_video_volume(**{**BASELINE, "bitrate_mbps": 1e308})


def test_upload_window_sets_average_effective_throughput():
    assert required_upload_mbps(uploaded_gb=720, upload_window_hours=8) == pytest.approx(200)
    assert required_upload_mbps(uploaded_gb=720, upload_window_hours=4) == pytest.approx(400)


def test_upload_bandwidth_uses_filtered_volume():
    volume = daily_video_volume(**BASELINE)
    assert required_upload_mbps(
        uploaded_gb=volume["uploaded_gb_per_day"], upload_window_hours=4
    ) == pytest.approx(400)


def test_no_upload_requires_zero_throughput():
    assert required_upload_mbps(uploaded_gb=0, upload_window_hours=4) == 0


@pytest.mark.parametrize("changes", [
    {"uploaded_gb": -1}, {"uploaded_gb": True},
    {"uploaded_gb": float("nan")}, {"uploaded_gb": float("inf")},
    {"upload_window_hours": 0}, {"upload_window_hours": -1},
    {"upload_window_hours": "4"}, {"upload_window_hours": float("inf")},
    {"uploaded_gb": 1e308}, {"upload_window_hours": 1e308},
])
def test_invalid_bandwidth_inputs_are_rejected(changes):
    with pytest.raises(ValueError):
        required_upload_mbps(**{**{"uploaded_gb": 720, "upload_window_hours": 4}, **changes})


STORAGE = {"daily_gb": 720, "retention_days": 30, "replicas": 3,
           "price_per_logical_gb_month": 0.10}


def test_storage_redundancy_does_not_multiply_logical_bill():
    result = storage_estimate(**STORAGE)
    assert result == pytest.approx({"logical_gb": 21600, "physical_gb": 64800,
                                    "monthly_cost": 2160})
    single = storage_estimate(**{**STORAGE, "replicas": 1})
    assert single["monthly_cost"] == result["monthly_cost"]
    assert single["physical_gb"] == result["logical_gb"]


def test_halving_retention_halves_capacity_and_monthly_cost():
    full = storage_estimate(**STORAGE)
    half = storage_estimate(**{**STORAGE, "retention_days": 15})
    for key in full:
        assert half[key] == pytest.approx(full[key] / 2)


@pytest.mark.parametrize("field", ["daily_gb", "retention_days"])
def test_empty_retained_dataset_has_zero_storage_cost(field):
    assert storage_estimate(**{**STORAGE, field: 0}) == {
        "logical_gb": 0, "physical_gb": 0, "monthly_cost": 0}


@pytest.mark.parametrize("changes", [
    {"daily_gb": -1}, {"daily_gb": float("inf")},
    {"retention_days": float("nan")}, {"retention_days": -1},
    {"price_per_logical_gb_month": -0.1}, {"price_per_logical_gb_month": True},
    {"replicas": 0}, {"replicas": 1.5}, {"replicas": True},
    {"daily_gb": 1e308},
])
def test_invalid_storage_assumptions_are_rejected(changes):
    with pytest.raises(ValueError):
        storage_estimate(**{**STORAGE, **changes})


COMPUTE = {"gpus": 8, "hours_per_run": 6, "runs_per_month": 30,
           "price_per_gpu_hour": 5}


def test_training_cost_uses_gpu_hours_not_wall_clock_hours():
    assert training_compute_cost(**COMPUTE) == pytest.approx({
        "gpu_hours_per_run": 48, "monthly_gpu_hours": 1440, "monthly_cost": 7200})


def test_more_gpus_and_shorter_runtime_can_cost_more():
    baseline = training_compute_cost(**COMPUTE)
    expanded = training_compute_cost(**{**COMPUTE, "gpus": 16, "hours_per_run": 4})
    assert expanded["gpu_hours_per_run"] == 64
    assert expanded["monthly_cost"] > baseline["monthly_cost"]


@pytest.mark.parametrize("field", ["gpus", "hours_per_run", "runs_per_month"])
def test_no_training_has_zero_monthly_compute_cost(field):
    result = training_compute_cost(**{**COMPUTE, field: 0})
    assert result["monthly_gpu_hours"] == 0
    assert result["monthly_cost"] == 0


@pytest.mark.parametrize("changes", [
    {"gpus": -1}, {"gpus": 1.5}, {"gpus": True},
    {"runs_per_month": -1}, {"runs_per_month": 1.5},
    {"hours_per_run": -1}, {"hours_per_run": float("nan")},
    {"price_per_gpu_hour": -1}, {"price_per_gpu_hour": float("inf")},
    {"hours_per_run": 1e308},
])
def test_invalid_compute_assumptions_are_rejected(changes):
    with pytest.raises(ValueError):
        training_compute_cost(**{**COMPUTE, **changes})


CHECKPOINT = {"recompute_gpu_hours": 8, "save_load_gpu_hours": 2,
              "price_per_gpu_hour": 5, "storage_io_monthly_cost": 30}


def test_checkpoint_accounts_for_compute_and_storage_separately():
    assert checkpoint_overhead(**CHECKPOINT) == pytest.approx({
        "extra_gpu_hours": 10, "extra_compute_cost": 50,
        "storage_io_monthly_cost": 30, "monthly_cost": 80})


def test_checkpoint_recompute_example_converts_minutes_to_hours():
    result = checkpoint_overhead(**{
        **CHECKPOINT, "recompute_gpu_hours": 8 * (10 / 60) * 6,
        "save_load_gpu_hours": 0, "storage_io_monthly_cost": 0})
    assert result["extra_gpu_hours"] == pytest.approx(8)
    assert result["monthly_cost"] == pytest.approx(40)


def test_zero_gpu_overhead_can_still_have_storage_cost():
    result = checkpoint_overhead(**{
        **CHECKPOINT, "recompute_gpu_hours": 0, "save_load_gpu_hours": 0})
    assert result["extra_compute_cost"] == 0
    assert result["monthly_cost"] == 30


def test_more_frequent_checkpoint_can_reduce_recompute_but_increase_total_cost():
    baseline = checkpoint_overhead(**CHECKPOINT)
    frequent = checkpoint_overhead(**{
        **CHECKPOINT, "recompute_gpu_hours": 4, "save_load_gpu_hours": 8})
    assert frequent["monthly_cost"] > baseline["monthly_cost"]


@pytest.mark.parametrize("field", list(CHECKPOINT))
@pytest.mark.parametrize("value", [-1, float("inf"), float("nan"), True])
def test_invalid_checkpoint_inputs_are_rejected(field, value):
    with pytest.raises(ValueError):
        checkpoint_overhead(**{**CHECKPOINT, field: value})


def test_checkpoint_sum_overflow_is_rejected():
    with pytest.raises(ValueError, match="超出"):
        checkpoint_overhead(**{
            **CHECKPOINT, "recompute_gpu_hours": 1e308, "save_load_gpu_hours": 1e308})


def test_costlier_plan_has_negative_savings_and_no_savings_payback():
    result = compare_costs(baseline_monthly_cost=10448, candidate_monthly_cost=11768,
                           upfront_cost=1000)
    assert result == {"monthly_savings": -1320, "payback_months": None}


def test_monthly_savings_repay_upfront_investment():
    result = compare_costs(baseline_monthly_cost=1000, candidate_monthly_cost=800,
                           upfront_cost=1000)
    assert result == {"monthly_savings": 200, "payback_months": 5}


def test_no_monthly_savings_has_no_payback_even_with_zero_investment():
    assert compare_costs(baseline_monthly_cost=1000, candidate_monthly_cost=1000) == {
        "monthly_savings": 0, "payback_months": None}


def test_no_upfront_cost_and_positive_savings_has_zero_payback_time():
    assert compare_costs(baseline_monthly_cost=1000, candidate_monthly_cost=800) == {
        "monthly_savings": 200, "payback_months": 0}


def test_payback_preserves_fractional_months():
    assert compare_costs(baseline_monthly_cost=1000, candidate_monthly_cost=800,
                         upfront_cost=500)["payback_months"] == 2.5


@pytest.mark.parametrize("field", ["baseline_monthly_cost", "candidate_monthly_cost", "upfront_cost"])
@pytest.mark.parametrize("value", [-1, float("inf"), float("nan"), True])
def test_invalid_comparison_inputs_are_rejected(field, value):
    with pytest.raises(ValueError):
        compare_costs(**{**{"baseline_monthly_cost": 1000, "candidate_monthly_cost": 800,
                            "upfront_cost": 1000}, field: value})


def test_payback_overflow_is_rejected():
    with pytest.raises(ValueError, match="超出"):
        compare_costs(baseline_monthly_cost=1e-308, candidate_monthly_cost=0,
                      upfront_cost=1e308)


@pytest.fixture
def baseline_config():
    path = Path(__file__).resolve().parents[1] / "scratch/robot-cost-lab/baseline.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_scenario_connects_baseline_and_sums_each_cost_once(baseline_config):
    result = estimate_scenario(baseline_config)
    assert result["video"]["uploaded_gb_per_day"] == 720
    assert result["upload"] == {"required_mbps": 400, "monthly_cost": 432}
    expected = {"raw_storage": 2160, "derived_storage": 1008,
                "training": 7200, "checkpoint": 80}
    for group, cost in expected.items():
        assert result[group]["monthly_cost"] == pytest.approx(cost)
    assert result["monthly_cost"] == pytest.approx(10880)


def test_upload_filter_propagates_without_implicitly_scaling_derived_data(baseline_config):
    baseline_config["video"]["upload_fraction"] = 0.125
    result = estimate_scenario(baseline_config)
    assert result["video"]["captured_gb_per_day"] == 2880
    assert result["video"]["uploaded_gb_per_day"] == 360
    assert result["upload"] == {"required_mbps": 200, "monthly_cost": 216}
    assert result["raw_storage"]["logical_gb"] == 10800
    assert result["raw_storage"]["monthly_cost"] == 1080
    assert result["derived_storage"]["monthly_cost"] == pytest.approx(1008)
    assert result["monthly_cost"] == pytest.approx(9584)


def test_upload_window_changes_throughput_not_per_gb_bill(baseline_config):
    baseline_config["upload"]["window_hours"] = 8
    assert estimate_scenario(baseline_config)["upload"] == {
        "required_mbps": 200, "monthly_cost": 432}


def test_scenario_does_not_mutate_input_or_add_cached_results(baseline_config):
    before = copy.deepcopy(baseline_config)
    estimate_scenario(baseline_config)
    assert baseline_config == before


@pytest.mark.parametrize("group,field,value", [
    ("upload", "days_per_month", 32), ("upload", "days_per_month", True),
    ("upload", "price_per_gb", -1), ("upload", "price_per_gb", float("inf")),
    ("upload", "price_per_gb", 1e308), ("video", "upload_fraction", 2),
    ("raw_storage", "replicas", 0),
])
def test_invalid_scenario_values_are_rejected(baseline_config, group, field, value):
    baseline_config[group][field] = value
    with pytest.raises(ValueError):
        estimate_scenario(baseline_config)


def test_raw_storage_rejects_a_stale_manual_daily_volume(baseline_config):
    baseline_config["raw_storage"]["daily_gb"] = 720
    with pytest.raises(ValueError, match="raw_storage"):
        estimate_scenario(baseline_config)


@pytest.mark.parametrize("config", [[], {}, {"name": "baseline"}])
def test_incomplete_or_non_object_scenario_is_rejected(config):
    with pytest.raises(ValueError):
        estimate_scenario(config)


def test_empty_scenario_name_is_rejected(baseline_config):
    baseline_config["name"] = " "
    with pytest.raises(ValueError, match="name"):
        estimate_scenario(baseline_config)


def test_load_real_config_then_estimate():
    path = Path(__file__).resolve().parents[1] / "scratch/robot-cost-lab/baseline.json"
    config = load_scenario(path)
    assert config["name"] == "baseline"
    assert estimate_scenario(config)["monthly_cost"] == pytest.approx(10880)


def test_load_preserves_chinese_names(tmp_path, baseline_config):
    baseline_config["name"] = "原方案"
    path = tmp_path / "方案.json"
    path.write_text(json.dumps(baseline_config, ensure_ascii=False), encoding="utf-8")
    assert load_scenario(str(path)) == baseline_config


def test_missing_config_has_readable_error(tmp_path):
    with pytest.raises(ValueError, match="无法读取"):
        load_scenario(tmp_path / "missing.json")


def test_non_utf8_config_has_readable_error(tmp_path):
    path = tmp_path / "broken.json"
    path.write_bytes(b"\xff")
    with pytest.raises(ValueError, match="UTF-8"):
        load_scenario(path)


def test_malformed_json_reports_line_and_column(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text('{\n "name": "baseline",\n}', encoding="utf-8")
    with pytest.raises(ValueError, match="第3行，第1列"):
        load_scenario(path)


@pytest.mark.parametrize("contents", ["[]", "null", '"baseline"', "123"])
def test_json_root_must_be_an_object(tmp_path, contents):
    path = tmp_path / "wrong-root.json"
    path.write_text(contents, encoding="utf-8")
    with pytest.raises(ValueError, match="最外层"):
        load_scenario(path)


def test_load_does_not_claim_to_validate_business_fields(tmp_path):
    path = tmp_path / "incomplete.json"
    path.write_text('{"name": "incomplete"}', encoding="utf-8")
    config = load_scenario(path)
    assert config == {"name": "incomplete"}
    with pytest.raises(ValueError):
        estimate_scenario(config)


def test_cli_single_scenario_outputs_json(capsys):
    path = Path(__file__).resolve().parents[1] / "scratch/robot-cost-lab/baseline.json"
    assert main([str(path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["baseline"]["monthly_cost"] == 10880
    assert "comparison" not in report
    assert "教学估算" in report["cost_scope"]


def test_cli_module_compares_real_configs_in_a_fresh_process():
    root = Path(__file__).resolve().parents[2]
    process = subprocess.run([
        sys.executable, "-m", "backend.scratch.robot_cost_model",
        "backend/scratch/robot-cost-lab/baseline.json", "--compare",
        "backend/scratch/robot-cost-lab/candidate.json", "--upfront-cost", "1000",
    ], cwd=root, capture_output=True, text=True, timeout=20)
    assert process.returncode == 0, process.stderr
    report = json.loads(process.stdout)
    assert report["baseline"]["monthly_cost"] == 10880
    assert report["candidate"]["monthly_cost"] == 12200
    assert report["comparison"] == {"monthly_savings": -1320, "payback_months": None}
    assert process.stderr == ""


def test_cli_missing_config_is_an_error_without_partial_report(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        main([str(tmp_path / "missing.json")])
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "无法读取" in captured.err
    assert "Traceback" not in captured.err


def test_cli_invalid_business_value_is_an_error(tmp_path, baseline_config, capsys):
    baseline_config["training"]["gpus"] = -8
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(baseline_config), encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        main([str(path)])
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "gpus" in captured.err


def test_cli_upfront_investment_requires_a_comparison(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["unused.json", "--upfront-cost", "1000"])
    assert exc.value.code == 2
    assert "必须与 --compare" in capsys.readouterr().err


def test_cli_comparison_rejects_nonfinite_upfront_investment(capsys):
    path = Path(__file__).resolve().parents[1] / "scratch/robot-cost-lab/baseline.json"
    with pytest.raises(SystemExit) as exc:
        main([str(path), "--compare", str(path), "--upfront-cost", "nan"])
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "upfront_cost" in captured.err

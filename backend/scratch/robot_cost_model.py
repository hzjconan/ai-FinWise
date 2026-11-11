"""L14：机器人数据平台成本估算，逐函数教学；不是实际云厂商报价。"""
import argparse
import json
import math
from pathlib import Path


def daily_video_volume(*, robots: int, cameras_per_robot: int,
                       bitrate_mbps: float, recording_hours: float,
                       upload_fraction: float = 1.0) -> dict[str, float]:
    """估算每日压缩视频采集 / 上传量；GB 为十进制，不含协议等额外开销。"""
    for name, value in (("robots", robots), ("cameras_per_robot", cameras_per_robot)):
        if type(value) is not int or value < 0:
            raise ValueError(f"{name} 必须为非负整数")
    for name, value in (("bitrate_mbps", bitrate_mbps), ("recording_hours", recording_hours),
                        ("upload_fraction", upload_fraction)):
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} 必须为有限非负数")
    if recording_hours > 24:
        raise ValueError("每天录制时长不能超过 24 小时")
    if upload_fraction > 1:
        raise ValueError("上传字节比例必须在 0～1 之间，例如 25% 写成 0.25")

    seconds = recording_hours * 3600
    bits_per_day = robots * cameras_per_robot * bitrate_mbps * 1_000_000 * seconds
    captured_gb = bits_per_day / 8 / 1_000_000_000
    if not math.isfinite(captured_gb):
        raise ValueError("数据量超出可表示范围，请检查输入")
    return {"captured_gb_per_day": captured_gb,
            "uploaded_gb_per_day": captured_gb * upload_fraction}


def required_upload_mbps(*, uploaded_gb: float, upload_window_hours: float) -> float:
    """在给定窗口内上传十进制 GB 所需的平均有效吞吐（Mbps）。"""
    for name, value in (("uploaded_gb", uploaded_gb),
                        ("upload_window_hours", upload_window_hours)):
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} 必须为有限非负数")
    if upload_window_hours == 0:
        raise ValueError("上传时间窗口必须大于 0 小时")

    total_bits = uploaded_gb * 1_000_000_000 * 8
    seconds = upload_window_hours * 3600
    mbps = total_bits / seconds / 1_000_000
    if not math.isfinite(total_bits) or not math.isfinite(seconds) or not math.isfinite(mbps):
        raise ValueError("计算超出可表示范围，请检查输入")
    return mbps


def storage_estimate(*, daily_gb: float, retention_days: float,
                     replicas: int, price_per_logical_gb_month: float) -> dict[str, float]:
    """稳定保留窗口的容量及按逻辑 GB 计费月费；物理占用仅计副本。"""
    for name, value in (("daily_gb", daily_gb), ("retention_days", retention_days),
                        ("price_per_logical_gb_month", price_per_logical_gb_month)):
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} 必须为有限非负数")
    if type(replicas) is not int or replicas < 1:
        raise ValueError("replicas 必须为正整数")

    logical_gb = daily_gb * retention_days
    physical_gb = logical_gb * replicas
    monthly_cost = logical_gb * price_per_logical_gb_month
    if not all(math.isfinite(value) for value in (logical_gb, physical_gb, monthly_cost)):
        raise ValueError("计算超出可表示范围，请检查输入")
    return {"logical_gb": logical_gb, "physical_gb": physical_gb,
            "monthly_cost": monthly_cost}


def training_compute_cost(*, gpus: int, hours_per_run: float,
                          runs_per_month: int, price_per_gpu_hour: float) -> dict[str, float]:
    """固定卡数训练的月 GPU 时间及按 GPU 小时折算的费用。"""
    for name, value in (("gpus", gpus), ("runs_per_month", runs_per_month)):
        if type(value) is not int or value < 0:
            raise ValueError(f"{name} 必须为非负整数")
    for name, value in (("hours_per_run", hours_per_run),
                        ("price_per_gpu_hour", price_per_gpu_hour)):
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} 必须为有限非负数")

    gpu_hours_per_run = gpus * hours_per_run
    monthly_gpu_hours = gpu_hours_per_run * runs_per_month
    monthly_cost = monthly_gpu_hours * price_per_gpu_hour
    if not all(math.isfinite(value) for value in
               (gpu_hours_per_run, monthly_gpu_hours, monthly_cost)):
        raise ValueError("计算超出可表示范围，请检查输入")
    return {"gpu_hours_per_run": gpu_hours_per_run,
            "monthly_gpu_hours": monthly_gpu_hours, "monthly_cost": monthly_cost}


def checkpoint_overhead(*, recompute_gpu_hours: float, save_load_gpu_hours: float,
                        price_per_gpu_hour: float,
                        storage_io_monthly_cost: float) -> dict[str, float]:
    """月度checkpoint额外开销；输入时间均为已汇总且未重复计入的GPU小时。"""
    for name, value in (("recompute_gpu_hours", recompute_gpu_hours),
                        ("save_load_gpu_hours", save_load_gpu_hours),
                        ("price_per_gpu_hour", price_per_gpu_hour),
                        ("storage_io_monthly_cost", storage_io_monthly_cost)):
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} 必须为有限非负数")

    extra_gpu_hours = recompute_gpu_hours + save_load_gpu_hours
    extra_compute_cost = extra_gpu_hours * price_per_gpu_hour
    monthly_cost = extra_compute_cost + storage_io_monthly_cost
    if not all(math.isfinite(value) for value in
               (extra_gpu_hours, extra_compute_cost, monthly_cost)):
        raise ValueError("计算超出可表示范围，请检查输入")
    return {"extra_gpu_hours": extra_gpu_hours,
            "extra_compute_cost": extra_compute_cost,
            "storage_io_monthly_cost": storage_io_monthly_cost,
            "monthly_cost": monthly_cost}


def compare_costs(*, baseline_monthly_cost: float, candidate_monthly_cost: float,
                  upfront_cost: float = 0) -> dict[str, float | None]:
    """同范围月费的净节省与简单回本月数；不省钱时回本月数为None。"""
    for name, value in (("baseline_monthly_cost", baseline_monthly_cost),
                        ("candidate_monthly_cost", candidate_monthly_cost),
                        ("upfront_cost", upfront_cost)):
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} 必须为有限非负数")

    monthly_savings = baseline_monthly_cost - candidate_monthly_cost
    payback_months = upfront_cost / monthly_savings if monthly_savings > 0 else None
    if payback_months is not None and not math.isfinite(payback_months):
        raise ValueError("回本时间超出可表示范围，请检查输入")
    return {"monthly_savings": monthly_savings, "payback_months": payback_months}


def estimate_scenario(config: dict) -> dict:
    """将教学配置串入各估算函数；仅汇总列明项目，不评估训练质量。"""
    fields = {
        "video": {"robots", "cameras_per_robot", "bitrate_mbps", "recording_hours", "upload_fraction"},
        "upload": {"window_hours", "days_per_month", "price_per_gb"},
        "raw_storage": {"retention_days", "replicas", "price_per_logical_gb_month"},
        "derived_storage": {"daily_gb", "retention_days", "replicas", "price_per_logical_gb_month"},
        "training": {"gpus", "hours_per_run", "runs_per_month", "price_per_gpu_hour"},
        "checkpoint": {"recompute_gpu_hours", "save_load_gpu_hours", "storage_io_monthly_cost"},
    }
    if type(config) is not dict or set(config) != {"name", *fields}:
        raise ValueError("配置必须包含name及规定的六组输入，不能缺少或增加字段")
    if not isinstance(config["name"], str) or not config["name"].strip():
        raise ValueError("name 必须为非空字符串")
    for group, expected in fields.items():
        if type(config[group]) is not dict or set(config[group]) != expected:
            raise ValueError(f"{group} 的字段缺失、多余或格式不正确")

    upload = config["upload"]
    days = upload["days_per_month"]
    price = upload["price_per_gb"]
    if type(days) is not int or not 0 <= days <= 31:
        raise ValueError("days_per_month 必须为0～31的整数")
    if type(price) not in (int, float) or not math.isfinite(price) or price < 0:
        raise ValueError("price_per_gb 必须为有限非负数")

    video = daily_video_volume(**config["video"])
    uploaded_gb = video["uploaded_gb_per_day"]
    required_mbps = required_upload_mbps(
        uploaded_gb=uploaded_gb, upload_window_hours=upload["window_hours"])
    upload_cost = uploaded_gb * days * price
    raw = storage_estimate(daily_gb=uploaded_gb, **config["raw_storage"])
    derived = storage_estimate(**config["derived_storage"])
    training = training_compute_cost(**config["training"])
    checkpoint = checkpoint_overhead(
        price_per_gpu_hour=config["training"]["price_per_gpu_hour"], **config["checkpoint"])
    monthly_cost = (upload_cost + raw["monthly_cost"] + derived["monthly_cost"]
                    + training["monthly_cost"] + checkpoint["monthly_cost"])
    if not math.isfinite(monthly_cost):
        raise ValueError("汇总费用超出可表示范围，请检查输入")
    return {"name": config["name"], "video": video,
            "upload": {"required_mbps": required_mbps, "monthly_cost": upload_cost},
            "raw_storage": raw, "derived_storage": derived,
            "training": training, "checkpoint": checkpoint, "monthly_cost": monthly_cost}


def load_scenario(path: str | Path) -> dict:
    """读取UTF-8 JSON对象；字段和单位范围由estimate_scenario检查。"""
    try:
        contents = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"无法读取UTF-8配置文件 {path}: {exc}") from exc
    try:
        config = json.loads(contents)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON格式错误（第{exc.lineno}行，第{exc.colno}列）：{exc.msg}") from exc
    if type(config) is not dict:
        raise ValueError("配置文件最外层必须是JSON对象，即使用花括号")
    return config


def main(argv: list[str] | None = None) -> int:
    """命令行入口：估算单个方案，或比较两份同口径配置。"""
    parser = argparse.ArgumentParser(description="L14机器人数据成本教学估算器")
    parser.add_argument("config", help="原方案JSON路径")
    parser.add_argument("--compare", help="可选：新方案JSON路径")
    parser.add_argument("--upfront-cost", type=float, default=0,
                        help="新方案一次性投入（元），仅与--compare一起使用")
    args = parser.parse_args(argv)
    if args.upfront_cost != 0 and not args.compare:
        parser.error("--upfront-cost 必须与 --compare 一起使用")

    try:
        baseline = estimate_scenario(load_scenario(args.config))
        report = {"cost_scope": "教学估算：上传流量、原始/派生存储、正常训练及checkpoint额外开销",
                  "baseline": baseline}
        if args.compare:
            candidate = estimate_scenario(load_scenario(args.compare))
            report["candidate"] = candidate
            report["comparison"] = compare_costs(
                baseline_monthly_cost=baseline["monthly_cost"],
                candidate_monthly_cost=candidate["monthly_cost"],
                upfront_cost=args.upfront_cost)
    except ValueError as exc:
        parser.error(str(exc))

    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

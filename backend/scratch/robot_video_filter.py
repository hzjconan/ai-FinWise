"""L12：对完整合成片段做低变化筛选，演示局部事件可能被漏掉。

仓库根目录运行：backend/.venv/bin/python -m backend.scratch.robot_video_filter
    --output-dir backend/scratch/robot-video-lab/filter-demo
仅生成新文件，不删除原片段；事件元数据是人工构造的保护信号。
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import subprocess

import imageio_ffmpeg
import numpy as np


PROTECTED_EVENTS = frozenset({"contact", "failure", "task_active"})


def synthetic_frames(kind: str) -> np.ndarray:
    frames = np.zeros((12, 100, 100, 3), dtype=np.uint8)
    if kind == "moving":
        for index, frame in enumerate(frames):
            x = 4 + index * 5
            frame[40:56, x:x + 16] = 255
    elif kind == "subtle":
        frames[6:8, 49:51, 49:51] = 255
    elif kind != "idle":
        raise ValueError(f"未知合成片段：{kind}")
    return frames


def make_fixture(folder: Path) -> dict:
    folder = Path(folder)
    names = ["idle", "moving", "subtle"]
    targets = [folder / f"{name}.mkv" for name in names]
    targets += [folder / "manifest.json", folder / "report.json"]
    if any(path.exists() for path in targets):
        raise FileExistsError("实验输出已存在，请复用报告或选择新目录，不覆盖原文件")
    folder.mkdir(parents=True, exist_ok=True)
    records = []
    for name in names:
        path = folder / f"{name}.mkv"
        # FFV1 / bgr0 保留此处 RGB 测试图像，避免有损编码干扰阈值实验。
        subprocess.run(
            [imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-nostdin", "-n",
             "-f", "rawvideo", "-pixel_format", "rgb24", "-video_size", "100x100",
             "-framerate", "6", "-i", "pipe:0", "-an", "-c:v", "ffv1",
             "-pix_fmt", "bgr0", "-threads", "1", str(path)],
            input=synthetic_frames(name).tobytes(), capture_output=True, check=True,
        )
        records.append({"clip_id": name, "file": path.name,
                        "events": ["contact"] if name == "subtle" else []})
    manifest = {"synthetic": True, "fps": 6, "clips": records}
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def motion_summary(frames) -> tuple[float, int]:
    """相邻帧全图平均绝对差的最大值，尺度 0～255；流式保留前一帧。"""
    previous = None
    maximum = 0.0
    count = 0
    for frame in frames:
        if frame.dtype != np.uint8 or frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError("需要 uint8 RGB 图像")
        current = frame.astype(np.float32)
        if previous is not None:
            if current.shape != previous.shape:
                raise ValueError("片段内图像尺寸不一致")
            maximum = max(maximum, float(np.abs(current - previous).mean()))
        previous = current
        count += 1
    if count < 2:
        raise ValueError("至少两帧才能比较相邻变化")
    return maximum, count


def decide(score: float, threshold: float, events=()) -> dict:
    if not math.isfinite(score) or score < 0:
        raise ValueError("变化分数必须为有限非负数")
    if not math.isfinite(threshold) or threshold < 0:
        raise ValueError("阈值必须为有限非负数")
    motion_keep = score >= threshold
    protected = bool(PROTECTED_EVENTS.intersection(events))
    return {"motion_only_keep": motion_keep,
            "event_guard_keep": motion_keep or protected,
            "protected_event": protected}


def analyze(folder: Path, manifest: dict, *, threshold=1.0) -> dict:
    # 先校验阈值，不将无效配置带入昂贵的视频解码。
    decide(0.0, threshold)
    rows = []
    for record in manifest["clips"]:
        path = Path(folder) / record["file"]
        reader = imageio_ffmpeg.read_frames(
            str(path), pix_fmt="rgb24", input_params=["-threads", "1"],
            output_params=["-threads", "1"],
        )
        try:
            metadata = next(reader)
            width, height = metadata["size"]
            images = (np.frombuffer(data, dtype=np.uint8).reshape(height, width, 3)
                      for data in reader)
            score, count = motion_summary(images)
        finally:
            reader.close()
        rows.append({"clip_id": record["clip_id"], "frames": count,
                     "fps": metadata["fps"], "bytes": path.stat().st_size,
                     "max_mean_change": score, "events": record["events"],
                     **decide(score, threshold, record["events"])})
    return {"synthetic": True, "threshold_0_to_255": threshold, "clips": rows,
            "input_bytes": sum(row["bytes"] for row in rows),
            "motion_only_selected_bytes": sum(row["bytes"] for row in rows
                                              if row["motion_only_keep"]),
            "event_guard_selected_bytes": sum(row["bytes"] for row in rows
                                              if row["event_guard_keep"])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--threshold", default=1.0, type=float)
    args = parser.parse_args()
    try:
        decide(0.0, args.threshold)
    except ValueError as error:
        parser.error(str(error))
    manifest = make_fixture(args.output_dir)
    report = analyze(args.output_dir, manifest, threshold=args.threshold)
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    (args.output_dir / "report.json").write_text(text)
    print(text, end="")
    print("合成素材；事件来自模拟元数据；仅选择完整片段，不删除源文件。")


if __name__ == "__main__":
    main()

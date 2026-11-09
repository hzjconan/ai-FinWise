"""L13：真实视频文件与示范动作配对；本模块只准备数据，不训练。

仓库根目录：backend/.venv/bin/python -m backend.scratch.robot_video_data
    --output-dir backend/scratch/robot-video-lab/training-demo-state
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import subprocess

import imageio_ffmpeg
import numpy as np
import torch
from torch.utils.data import DataLoader, Dataset


def make_fixture(folder: Path, *, episodes=16, seed=42) -> Path:
    """每个 episode 一个视频；最后四个留作验证，正负动作均衡。"""
    if episodes < 8 or episodes % 4:
        raise ValueError("episode 数需至少 8，且为 4 的倍数")
    folder = Path(folder)
    paths = [folder / f"episode-{i:03d}.mkv" for i in range(episodes)]
    manifest_path = folder / "manifest.json"
    if any(path.exists() for path in [manifest_path, *paths]):
        raise FileExistsError("数据已存在，请复用清单或选择新目录，不覆盖原数据")
    folder.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    records = []
    for episode, path in enumerate(paths):
        dx = (-2, -1, 1, 2)[episode % 4]
        shift = dx * 7
        x = int(rng.integers(2 - min(0, shift), 27 - max(0, shift)))
        y = int(rng.integers(2, 27))
        frames = np.zeros((8, 32, 32, 3), dtype=np.uint8)
        positions, actions = [], []
        for index, frame in enumerate(frames):
            frame[y:y + 4, x:x + 4] = 255
            positions.append([x, y])
            if index < 7:
                # 先记录示范控制器的动作，再施加到下一时刻，不从未来图像猜标签。
                actions.append(float(dx))
                x += dx
        subprocess.run(
            [imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-nostdin", "-n",
             "-f", "rawvideo", "-pixel_format", "rgb24", "-video_size", "32x32",
             "-framerate", "8", "-i", "pipe:0", "-c:v", "ffv1", "-pix_fmt", "bgr0",
             "-threads", "1", "-an", str(path)],
            input=frames.tobytes(), capture_output=True, check=True,
        )
        records.append({"episode_id": f"episode-{episode:03d}", "video": path.name,
                        "split": "val" if episode >= episodes - 4 else "train",
                        "timestamps_s": [i / 8 for i in range(8)],
                        "state_timestamps_s": [i / 8 for i in range(8)],
                        "actions_dx": actions, "positions_xy": positions})
    manifest = {"schema_version": 2, "synthetic": True, "seed": seed, "fps": 8,
                "frame_size": [32, 32], "window_frames": 3,
                "action_unit": "horizontal pixels per 1/8 second; right is positive",
                "state_source": "simulated controller position, not a real sensor",
                "state_unit": "square top-left x,y in pixels",
                "episodes": records}
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest_path


def decode_rgb(path: Path) -> tuple[np.ndarray, dict]:
    reader = imageio_ffmpeg.read_frames(
        str(path), pix_fmt="rgb24", input_params=["-threads", "1"],
        output_params=["-threads", "1"],
    )
    try:
        metadata = next(reader)
        width, height = metadata["size"]
        arrays = [np.frombuffer(data, dtype=np.uint8).reshape(height, width, 3).copy()
                  for data in reader]
    finally:
        reader.close()
    if not arrays:
        raise ValueError("视频没有可解码帧")
    return np.stack(arrays), metadata


class VideoActionDataset(Dataset):
    """本地小实验一次解码并缓存所选 split；不是生产流式读取性能示范。"""

    def __init__(self, manifest_path: Path, *, split="train"):
        if split not in {"train", "val"}:
            raise ValueError("split 必须为 train 或 val")
        manifest_path = Path(manifest_path)
        self.manifest = json.loads(manifest_path.read_text())
        if self.manifest["schema_version"] != 2:
            raise ValueError("需要含模拟状态的 schema_version=2，请使用新目录生成数据")
        self.videos = {}
        self.records = []
        # x、y 各自按图像坐标最大值归一化；本课都是 32×32，即除以 31。
        self.state_scale = torch.tensor(self.manifest["frame_size"], dtype=torch.float32) - 1
        window = self.manifest["window_frames"]
        for episode in self.manifest["episodes"]:
            if episode["split"] != split:
                continue
            arrays, metadata = decode_rgb(manifest_path.parent / episode["video"])
            times, actions = episode["timestamps_s"], episode["actions_dx"]
            if (len(arrays) != len(times) or len(actions) != len(times) - 1
                    or arrays.shape[1:3] != tuple(reversed(self.manifest["frame_size"]))
                    or not math.isclose(metadata["fps"], self.manifest["fps"])):
                raise ValueError("视频与动作 / 时间元信息不一致")
            if any(not math.isfinite(t) for t in times) or any(
                b <= a for a, b in zip(times, times[1:])
            ):
                raise ValueError("时间戳必须严格递增")
            # 教学数据同为 8 Hz、同一时钟；不暗中按索引处理异步传感器。
            if episode["state_timestamps_s"] != times:
                raise ValueError("模拟状态时间戳必须与对应视频帧一致")
            positions = np.asarray(episode["positions_xy"], dtype=np.float32)
            if (positions.shape != (len(times), 2) or not np.isfinite(positions).all()
                    or np.any(positions < 0)
                    or np.any(positions > self.state_scale.numpy())):
                raise ValueError("模拟位置须为帧数×2的有限图像坐标")
            tensor = torch.from_numpy(arrays).permute(0, 3, 1, 2).float().div_(255)
            self.videos[episode["episode_id"]] = tensor
            # 末帧没有下一步实际动作，不能拿来作窗口末端。
            for anchor in range(window - 1, len(arrays) - 1):
                self.records.append({"episode_id": episode["episode_id"],
                                     "anchor_frame": anchor,
                                     "frame_indices": list(range(anchor - window + 1, anchor + 1)),
                                     "timestamps_s": times[anchor - window + 1:anchor + 1],
                                     "state_xy": positions[anchor].tolist(),
                                     "state_time_s": episode["state_timestamps_s"][anchor],
                                     "action_interval_s": times[anchor:anchor + 2],
                                     "action_dx": actions[anchor]})
        if not self.records:
            raise ValueError("所选 split 没有训练窗口")

    def __len__(self):
        return len(self.records)

    def __getitem__(self, index):
        record = self.records[index]
        video = self.videos[record["episode_id"]]
        indices = record["frame_indices"]
        state_xy = torch.tensor(record["state_xy"], dtype=torch.float32)
        return {"images": video[indices[0]:indices[-1] + 1].clone(),
                "state": state_xy / self.state_scale,
                "state_xy": state_xy,
                "state_time_s": torch.tensor(record["state_time_s"], dtype=torch.float64),
                "action": torch.tensor([record["action_dx"]], dtype=torch.float32),
                "episode_id": record["episode_id"],
                "anchor_frame": record["anchor_frame"],
                "frame_indices": torch.tensor(indices),
                "timestamps_s": torch.tensor(record["timestamps_s"], dtype=torch.float64),
                "action_interval_s": torch.tensor(record["action_interval_s"], dtype=torch.float64)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    torch.set_num_threads(1)
    manifest = make_fixture(args.output_dir)
    for split in ("train", "val"):
        dataset = VideoActionDataset(manifest, split=split)
        sample = dataset[0]
        batch = next(iter(DataLoader(dataset, batch_size=8, num_workers=0, shuffle=False)))
        print(f"{split}: episodes={len(dataset.videos)}, windows={len(dataset)}, "
              f"sample_images={list(sample['images'].shape)}, batch_images={list(batch['images'].shape)}")
        print(f"  first={sample['episode_id']} frames={sample['frame_indices'].tolist()} "
              f"times={sample['timestamps_s'].tolist()} action={sample['action'].tolist()} "
              f"action_interval={sample['action_interval_s'].tolist()}")
        print(f"  state_xy={sample['state_xy'].tolist()} state={sample['state'].tolist()} "
              f"state_time_s={sample['state_time_s'].item()} "
              f"batch_state={list(batch['state'].shape)}")
    print("只验证视频、模拟状态与示范动作配对，尚未创建模型或更新参数。")


if __name__ == "__main__":
    main()

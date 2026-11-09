"""L13：CPU、num_workers=0、整轮边界的单写者 checkpoint 教学。"""
import copy
import hashlib
import os
from pathlib import Path
import random
import tempfile

import numpy as np
import torch


def save_checkpoint(path: Path, model, optimizer, *, completed_epoch: int,
                    global_step: int, manifest_path: Path, config: dict,
                    train_generator: torch.Generator,
                    val_generator: torch.Generator) -> Path:
    """先写临时文件，再发布完整文件；不覆盖已有版本，不处理分布式保存。"""
    if (type(completed_epoch) is not int or type(global_step) is not int
            or completed_epoch < 0 or global_step < 0):
        raise ValueError("已完成轮数和更新次数必须为非负整数")
    path = Path(path)
    if path.exists():
        raise FileExistsError("checkpoint 已存在，请选择新版本路径，不覆盖旧进度")
    payload = {
        "format_version": 1,
        "model": model.state_dict(),
        "optimizer": optimizer.state_dict(),
        "completed_epoch": completed_epoch,
        "global_step": global_step,
        "config": copy.deepcopy(config),
        "manifest_sha256": hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest(),
        "rng": {
            "python": random.getstate(),
            "numpy": np.random.get_state(),
            "torch": torch.get_rng_state(),
            "train_loader": train_generator.get_state(),
            "val_loader": val_generator.get_state(),
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as handle:
            temporary = Path(handle.name)
            torch.save(payload, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path


def load_checkpoint(path: Path, model, optimizer, *, manifest_path: Path,
                    expected_config: dict, train_generator: torch.Generator,
                    val_generator: torch.Generator, restore_optimizer=True) -> dict:
    """恢复本课自己生成的本地文件；关闭 optimizer 恢复仅用于后续受控对照。"""
    # 包含 NumPy RNG，使用完整反序列化；输入限本课可信本地产物。
    payload = torch.load(Path(path), map_location="cpu", weights_only=False)
    required = {"format_version", "model", "optimizer", "completed_epoch", "global_step",
                "config", "manifest_sha256", "rng"}
    if not isinstance(payload, dict) or not required.issubset(payload):
        raise ValueError("checkpoint 缺少必要字段")
    if payload["format_version"] != 1:
        raise ValueError("不支持的 checkpoint 格式版本")
    if payload["config"] != expected_config:
        raise ValueError("checkpoint 配置与当前任务不一致")
    fingerprint = hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest()
    if payload["manifest_sha256"] != fingerprint:
        raise ValueError("checkpoint 数据清单与当前任务不一致")
    if any(type(payload[key]) is not int or payload[key] < 0
           for key in ("completed_epoch", "global_step")):
        raise ValueError("checkpoint 进度无效")
    rng = payload["rng"]
    if not isinstance(rng, dict) or not {
        "python", "numpy", "torch", "train_loader", "val_loader",
    }.issubset(rng):
        raise ValueError("checkpoint 缺少随机状态")
    current = model.state_dict()
    saved = payload["model"]
    if (not isinstance(saved, dict) or saved.keys() != current.keys()
            or any(not isinstance(saved[key], torch.Tensor)
                   or saved[key].shape != value.shape or saved[key].dtype != value.dtype
                   for key, value in current.items())):
        raise ValueError("checkpoint 模型结构或参数类型不兼容")
    model.load_state_dict(saved, strict=True)
    if restore_optimizer:
        optimizer.load_state_dict(payload["optimizer"])
    # 所有模型 / 优化器创建和加载完成后再恢复随机状态。
    random.setstate(rng["python"])
    np.random.set_state(rng["numpy"])
    torch.set_rng_state(rng["torch"])
    train_generator.set_state(rng["train_loader"])
    val_generator.set_state(rng["val_loader"])
    return {"completed_epoch": payload["completed_epoch"], "global_step": payload["global_step"],
            "config": copy.deepcopy(payload["config"]), "optimizer_restored": restore_optimizer}

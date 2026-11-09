"""L13：训练操作逐步实现；当前提供更新、整轮、独立评估和多轮训练。"""
import torch
from torch import nn


def train_step(model, optimizer, batch) -> float:
    """更新一次参数，返回本次更新前预测对应的 batch MSE。"""
    model.train()
    optimizer.zero_grad(set_to_none=True)
    prediction = model(batch["images"], batch["state"])
    target = batch["action"]
    if prediction.shape != target.shape or prediction.dtype != target.dtype:
        raise ValueError("预测和动作标签必须具有相同形状与类型，避免错误广播")
    loss = nn.MSELoss()(prediction, target)
    if not torch.isfinite(loss):
        raise ValueError("loss 必须为有限数值，拒绝更新参数")
    loss.backward()
    optimizer.step()
    return loss.detach().item()


def train_epoch(model, optimizer, loader) -> dict:
    """遍历整轮；损失按样本数加权，来自各批次更新前的预测。"""
    weighted_loss = 0.0
    samples = 0
    steps = 0
    for batch in loader:
        count = batch["action"].shape[0]
        if count == 0:
            raise ValueError("训练 batch 不能没有样本")
        loss = train_step(model, optimizer, batch)
        weighted_loss += loss * count
        samples += count
        steps += 1
    if samples == 0:
        raise ValueError("训练数据不能为空")
    return {"train_mse": weighted_loss / samples, "samples": samples, "steps": steps}


@torch.no_grad()
def evaluate(model, loader) -> dict:
    """固定当前参数评估整个数据集；返回后恢复先前训练 / 评估模式。"""
    was_training = model.training
    model.eval()
    weighted_loss = 0.0
    samples = 0
    try:
        for batch in loader:
            prediction = model(batch["images"], batch["state"])
            target = batch["action"]
            if prediction.shape != target.shape or prediction.dtype != target.dtype:
                raise ValueError("预测和动作标签必须具有相同形状与类型，避免错误广播")
            loss = nn.MSELoss()(prediction, target)
            if not torch.isfinite(loss):
                raise ValueError("评估 loss 必须为有限数值")
            count = target.shape[0]
            weighted_loss += loss.item() * count
            samples += count
    finally:
        model.train(was_training)
    if samples == 0:
        raise ValueError("评估数据不能为空")
    return {"mse": weighted_loss / samples, "samples": samples}


def fit(model, optimizer, train_loader, val_loader, *, epochs=30) -> list[dict]:
    """记录初始化与每轮结果，不重置模型 / 优化器，不保存 checkpoint。"""
    if epochs < 1:
        raise ValueError("epochs 必须为正整数")
    baseline = evaluate(model, val_loader)
    history = [{"epoch": 0, "train_mse": None, "val_mse": baseline["mse"],
                "train_samples": 0, "val_samples": baseline["samples"], "steps": 0}]
    for epoch in range(1, epochs + 1):
        training = train_epoch(model, optimizer, train_loader)
        validation = evaluate(model, val_loader)
        history.append({"epoch": epoch, "train_mse": training["train_mse"],
                        "val_mse": validation["mse"], "train_samples": training["samples"],
                        "val_samples": validation["samples"], "steps": training["steps"]})
    return history

"""L13：固定三帧 32×32 RGB 与当前二维模拟状态的教学小模型。"""
import torch
from torch import nn


class VideoStateModel(nn.Module):
    """小 MLP，仅用于学习训练流程，不代表生产视频策略架构。"""

    def __init__(self):
        super().__init__()
        self.video_encoder = nn.Sequential(
            nn.Flatten(start_dim=1),
            nn.Linear(3 * 3 * 32 * 32, 32),
            nn.ReLU(),
        )
        self.action_head = nn.Sequential(
            nn.Linear(32 + 2, 16),
            nn.ReLU(),
            nn.Linear(16, 1),
        )

    def forward(self, images, state):
        if images.ndim != 5 or tuple(images.shape[1:]) != (3, 3, 32, 32):
            raise ValueError("images 形状必须为 [batch,3帧,3通道,32,32]")
        if tuple(state.shape) != (images.shape[0], 2):
            raise ValueError("state 形状必须为 [相同batch,2]")
        if images.dtype != torch.float32 or state.dtype != torch.float32:
            raise ValueError("本课模型输入使用 float32")
        video_features = self.video_encoder(images)
        features = torch.cat([video_features, state], dim=1)
        return self.action_head(features)

"""L04 · 第 8 步动手：看 tokenizer 的真实产物 + 自己实现采样

讲义：docs/ai-agent-learning/lessons/L04-llm-inference-internals.md（第 2 步 Tokenizer、第 7 步采样）

四个小实验：
  8a 看 e5 tokenizer 的产物：input_ids / tokens / 特殊 token（不用写代码，看输出）
  8b 补齐（padding）：一批长短不一的句子 → 短的补 <pad>，attention_mask 里补的位置是 0
     TODO 8b：用 attention_mask 数出每句真实 token 数
  8c 中英文 token 数对比（不用写代码，看输出）
  8d 采样：TODO 8d-1 带温度的 softmax；TODO 8d-2 top-p 截断 + 重新归一化；然后掷 10000 次骰子看频率

只用本地已缓存的 multilingual-e5-small 的 tokenizer（不调 LLM、不联网）。

运行：
    cd backend && .venv/bin/python scratch/s1_05_tokenizer_sampling.py
测试：
    cd backend && .venv/bin/python -m pytest scratch/test_s1_05_tokenizer_sampling.py -v
"""
from __future__ import annotations

import os

import numpy as np

os.environ.setdefault("HF_HUB_OFFLINE", "1")     # 只用本地缓存（s4_01 时已下载过）
MODEL_NAME = "intfloat/multilingual-e5-small"

# 第 7 步课上的例子："我想给爸妈存一笔___"
CANDIDATES = ["钱", "养老", "定期", "股票"]
LOGITS = np.array([2.0, 1.0, 0.5, -1.0])


def load_tokenizer():
    from transformers import AutoTokenizer
    return AutoTokenizer.from_pretrained(MODEL_NAME)


# ========================= TODO 8b：用 attention_mask 数真实 token =========================

def real_token_counts(attention_mask: list[list[int]]) -> list[int]:
    """TODO 8b：返回每一句的真实 token 数（不算补齐的 <pad>）。

    attention_mask 每一行对应一句话：1 = 真实 token（包括 <s> </s>），0 = 补齐出来的 <pad>。
    例：[[1, 1, 1, 0, 0], [1, 1, 1, 1, 1]] → [3, 5]
    """
    return [sum(row) for row in attention_mask]


# ========================= TODO 8d-1：带温度的 softmax =========================

def softmax_with_temperature(logits: np.ndarray, temperature: float) -> np.ndarray:
    """TODO 8d-1：P(i) = e^(zᵢ / T) ÷ Σⱼ e^(zⱼ / T)

    提示：np.exp(x) 对数组逐个求指数；数组除以 .sum() 就是归一化。
    （真实实现会先减去最大值再求指数，防止数值溢出：结果不变，因为分子分母同乘了一个常数。可选）
    """
    shifted = logits / temperature
    shifted = shifted - shifted.max()   # 数值稳定：减去最大值
    exp = np.exp(shifted)
    return exp / exp.sum()


# ========================= TODO 8d-2：top-p 截断 + 重新归一化 =========================

def top_p_filter(probs: np.ndarray, p: float) -> np.ndarray:
    """TODO 8d-2：按概率从高到低累加，加到 ≥ p 就停，保留到这里为止的候选；
    其他候选概率置 0，再重新归一化（加起来等于 1）。返回的数组顺序和输入一致。

    例：[0.61, 0.22, 0.14, 0.03]，p = 0.8 → [0.73, 0.27, 0, 0]（课上算过）
    提示（可以一步步来）：
      order = np.argsort(probs)[::-1]           # 从大到小的下标：[0, 1, 2, 3]
      cumulative = np.cumsum(probs[order])      # 累加：[0.61, 0.83, 0.97, 1.0]
      保留几个？= 第一个 cumulative ≥ p 的位置 + 1（可以用 np.argmax(cumulative >= p) 找到这个位置）
    """
    order = np.argsort(probs)[::-1]          # 从大到小的下标
    cumulative = np.cumsum(probs[order])     # 累加概率
    # 用 np.where 而不是 np.argmax：避免浮点数误差导致 cumulative[-1] 略小于 p 时
    # np.argmax(cumulative >= p) 全 False 返回 0（只保留 1 个）的边界问题
    crossings = np.where(cumulative >= p)[0]
    keep_count = crossings[0] + 1 if len(crossings) > 0 else len(probs)
    mask = np.zeros_like(probs)
    mask[order[:keep_count]] = 1.0
    filtered = probs * mask
    return filtered / filtered.sum()

# =============================================================================


def sample_frequencies(probs: np.ndarray, n: int = 10000, seed: int = 0) -> np.ndarray:
    """按概率掷 n 次骰子，返回每个候选被抽中的频率。"""
    rng = np.random.default_rng(seed)
    picks = rng.choice(len(probs), size=n, p=probs)
    return np.bincount(picks, minlength=len(probs)) / n


def fmt(values: np.ndarray) -> str:
    return "  ".join(f"{c} {v:.3f}" for c, v in zip(CANDIDATES, values))


def main() -> None:
    tok = load_tokenizer()

    print("== 8a tokenizer 的产物 ==")
    enc = tok("我想给爸妈存一笔养老钱")
    print("  input_ids:", enc["input_ids"])
    print("  tokens:   ", tok.convert_ids_to_tokens(enc["input_ids"]))
    print(f"  特殊 token：开头 {tok.cls_token}（id {tok.cls_token_id}）、结尾 {tok.sep_token}（id {tok.sep_token_id}）、"
          f"补齐 {tok.pad_token}（id {tok.pad_token_id}）")

    print("\n== 8b 补齐（padding）==")
    batch = tok(["养老", "我想给爸妈存一笔养老钱"], padding=True)
    for ids, mask in zip(batch["input_ids"], batch["attention_mask"]):
        print("  ", tok.convert_ids_to_tokens(ids))
        print("   attention_mask:", mask)
    print("  每句真实 token 数：", real_token_counts(batch["attention_mask"]))

    print("\n== 8c 中英文 token 数对比（不含 <s> </s>）==")
    for text in ["我想给爸妈存一笔养老钱", "I want to save some retirement money for my parents"]:
        n = len(tok(text, add_special_tokens=False)["input_ids"])
        print(f"  {len(text):>3} 个字符 → {n:>2} 个 token  每个 token ≈ {len(text) / n:.1f} 个字符：{text}")

    print("\n== 8d 采样 ==")
    for t in (0.5, 1.0, 2.0):
        print(f"  T={t}:  {fmt(softmax_with_temperature(LOGITS, t))}")
    probs = softmax_with_temperature(LOGITS, 1.0)
    kept = top_p_filter(probs, 0.8)
    print(f"  top-p=0.8 后：{fmt(kept)}")
    print(f"  掷 10000 次的频率（T=1）：      {fmt(sample_frequencies(probs))}")
    print(f"  掷 10000 次的频率（top-p=0.8）：{fmt(sample_frequencies(kept))}")


if __name__ == "__main__":
    main()

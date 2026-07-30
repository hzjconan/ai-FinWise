"""阶段四 · s4_01：最小 RAG（本地 embedding）——语义检索 FinWise 产品

目标：把 RAG 的地基「向量化 → 余弦相似度 → top-k」这条**检索链路**亲手跑通。
刻意不用向量数据库、不用框架——内存 list + numpy 手算余弦，先看清「向量库到底在干什么」。

本脚本只做**检索**（retrieve）：给一句自然语言 query，返回最相关的几个产品。
「检索 → 拼进 prompt → 让模型作答」的生成部分留到 s4_02；TF-IDF 对照留到 s4_03。

★ 设计成「可插拔 encoder」：检索核心（cosine / top-k）只写一次，这里接 embedding，
  s4_03 换成 TF-IDF——同一套 query、同一套检索，只换 encoder，看质量差异（阶段四验收：
  "能解释 embedding 检索为什么比关键词匹配强" 就是这个 A/B）。

前置：
    cd backend && .venv/bin/pip install sentence-transformers numpy
    （首次运行会下载 multilingual-e5-small 权重，几百 MB，之后有缓存）

运行：
    cd backend && .venv/bin/python scratch/s4_01_rag_embedding.py
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    raise SystemExit(
        "缺 sentence-transformers。先装：\n"
        "  cd backend && .venv/bin/pip install sentence-transformers numpy"
    )


# ---------- 语料：FinWise 产品文档（name + 一句话卖点，覆盖不同语义需求）----------
# 真实系统里这些来自 Product 表的 name/description/investment_direction；这里内联一小批，
# 便于聚焦检索本身。刻意让「用户问法」和「文档措辞」不字面重合，才能看出语义检索的价值。
CORPUS: list[dict] = [
    {"code": "P-MMF", "name": "稳盈货币A",
     "text": "货币市场基金，随时申购赎回，几乎无波动，适合放随时可能用到的活钱和应急备用金。"},
    {"code": "P-PENSION", "name": "安心养老目标2040",
     "text": "养老目标日期基金，长期持有，权益仓位随临近退休逐年下降，为退休储备而设计。"},
    {"code": "P-TECH", "name": "科技创新股票",
     "text": "股票型基金，重仓科技成长企业，波动大、回撤深，适合能承受大幅亏损、追求高收益的进取投资者。"},
    {"code": "P-BOND", "name": "稳健纯债债券",
     "text": "纯债基金，以票息收益为主，波动很小，适合厌恶本金损失、只求稳稳收益的保守投资者。"},
    {"code": "P-GOLD", "name": "黄金ETF联接",
     "text": "跟踪黄金价格，与股债相关性低，通胀上行或市场动荡时常作为避险与对冲配置。"},
    {"code": "P-SHORTBOND", "name": "短债30天持有",
     "text": "短期债券基金，收益略高于货币基金，最短持有30天，兼顾一定流动性与收益。"},
    {"code": "P-MIX", "name": "灵活配置混合",
     "text": "股债灵活配置的混合基金，中等波动，攻守兼备，适合风险偏好适中的平衡型投资者。"},
]

# 测试查询：都是「语义」需求，字面上未必和文档词汇重合——正是关键词匹配的软肋。
QUERIES = [
    "有没有适合养老、能放很多年的产品？",
    "我想要能随时取出来、基本不会亏的",
    "能接受大波动，想博一把高收益",
    "有什么能抗通胀、避险的吗？",
]


# ---------- 可插拔 encoder 接口 ----------
class Encoder(ABC):
    """把文本编码成向量。文档和 query 分开两个方法——因为有些模型（如 e5）对两者用不同前缀。"""

    @abstractmethod
    def encode_docs(self, texts: list[str]) -> np.ndarray:
        """把 N 篇文档编码成 (N, dim) 矩阵。"""

    @abstractmethod
    def encode_query(self, text: str) -> np.ndarray:
        """把 1 条 query 编码成 (dim,) 向量。"""


class EmbeddingEncoder(Encoder):
    """本地 embedding 模型（multilingual-e5-small）。

    ★ e5 系列有个关键约定：文档要加前缀 "passage: "、查询要加前缀 "query: "。
      不加前缀检索质量会明显变差——这是个真实、非直觉的坑，记一下。
    """

    def __init__(self, model_name: str = "intfloat/multilingual-e5-small"):
        print(f"[加载模型] {model_name} …（首次会下载权重）")
        self.model = SentenceTransformer(model_name)

    def encode_docs(self, texts: list[str]) -> np.ndarray:
        prefixed = [f"passage: {t}" for t in texts]
        return self.model.encode(prefixed, normalize_embeddings=False)

    def encode_query(self, text: str) -> np.ndarray:
        return self.model.encode(f"query: {text}", normalize_embeddings=False)


# ========================= 检索核心（★ 你来填）=========================
# 这两个函数是「检索原理」的全部——向量化之后的一切都在这里。写一次，embedding 和
# 之后的 TF-IDF 都复用它们（这就是为什么 encoder 要可插拔）。

def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """TODO#1：返回向量 a、b 的余弦相似度 ∈ [-1, 1]。
    公式：dot(a, b) / (‖a‖ · ‖b‖)。
    提示：np.dot(a, b)、np.linalg.norm(a)。注意分母为 0 的兜底（空向量返回 0.0）。
    """
    denom = (np.linalg.norm(a) * np.linalg.norm(b))
    return  0.0 if denom == 0 else np.dot(a, b) / denom

def retrieve_top_k(query_vec: np.ndarray, doc_vecs: np.ndarray, k: int) -> list[tuple[int, float]]:
    """TODO#2：返回与 query 最相似的 k 篇文档，形如 [(doc_index, score), ...]，按 score 降序。
    提示：
      - doc_vecs 是 (N, dim)，逐行和 query_vec 算 cosine_similarity；
      - 收集 (i, score) 后按 score 排序取前 k；
      - 先跑通朴素版（for 循环）即可，别急着向量化优化。
    """
    scores = []
    docs_count = len(doc_vecs)
    for i in range(docs_count):
        scores.append((i, cosine_similarity(query_vec, doc_vecs[i])))
    return sorted(scores, key=lambda x: x[1], reverse=True)[:k]
        
# =====================================================================


def main() -> None:
    encoder = EmbeddingEncoder()

    # 1) 把语料编码成向量矩阵（只需一次；真实系统里这步离线预计算、存起来）
    doc_texts = [d["text"] for d in CORPUS]
    doc_vecs = encoder.encode_docs(doc_texts)
    print(f"[已编码] {len(CORPUS)} 篇文档 → 向量矩阵 {np.asarray(doc_vecs).shape}\n")

    # 2) 逐条 query：编码 → 检索 top-k → 打印
    for q in QUERIES:
        query_vec = encoder.encode_query(q)
        hits = retrieve_top_k(query_vec, np.asarray(doc_vecs), k=2)
        print(f"❓ {q}")
        for idx, score in hits:
            print(f"    {score:.3f}  {CORPUS[idx]['name']} —— {CORPUS[idx]['text']}")
        print()


if __name__ == "__main__":
    main()

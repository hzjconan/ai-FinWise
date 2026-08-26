"""阶段四 · s4_05：从「内存暴力检索」升级到「向量数据库」（Chroma）

承接 s4_01：那里你手搓了 RAG 地基——内存 list + numpy 手算余弦 + for 循环逐条比对（O(N) 暴力）。
本节把它换成真正的向量数据库 **Chroma**，亲手体验向量库相对手搓版**多给了什么**：

  1. 持久化    ——落盘。建一次库、反复用；进程重启数据还在（手搓版一停就没、每次重算）。
  2. 元数据过滤 ——「先按 风险等级=C3 过滤，再在子集里做相似度检索」。手搓版做不到。
  3. collection API——add / query 一把梭，索引/存储/检索都封装好。

★ 本质没变：还是「文本→向量→比相似度→top-K」，和 s4_01 一模一样。Chroma 只是把这套
  做到**能落盘、能过滤、能扛量**（内部用 HNSW 近似最近邻索引，几百万向量也毫秒级）。
  ——所以你 s4_01 手搓那一遍不是白费，正因为看过内部，才知道 Chroma 在替你干嘛。

⚠️ 两个必须记的坑：
  - Chroma 返回的是 **distance（距离，越小越近）**，不是相似度。我们把 collection 建成
    **cosine 空间**，此时 `distance = 1 - 余弦相似度`（范围 0~2，0 最近）。
  - 默认空间其实是 L2（欧氏），不是余弦——文本检索要**显式指定 cosine**，否则结果会怪。

前置：
    cd backend && .venv/bin/pip install chromadb        # sentence-transformers/numpy 已装
运行：
    cd backend && .venv/bin/python scratch/s4_05_vector_db_chroma.py
测试：
    cd backend && .venv/bin/python -m pytest scratch/test_s4_05_vector_db_chroma.py -v
"""
from __future__ import annotations

import os
import tempfile
from abc import ABC, abstractmethod

import numpy as np

try:
    import chromadb
except ImportError:
    raise SystemExit("缺 chromadb。先装：cd backend && .venv/bin/pip install chromadb")


# ---------- 语料：FinWise 产品（比 s4_01 多带 risk_level / category 两个「元数据」）----------
# 元数据是向量库的关键增值：它让你能「先按结构化条件过滤，再做语义检索」。
PRODUCTS: list[dict] = [
    {"code": "P-MMF",       "name": "稳盈货币A",        "risk_level": "C2", "category": "货币",
     "text": "货币市场基金，随时申购赎回，几乎无波动，适合放随时可能用到的活钱和应急备用金。"},
    {"code": "P-BOND",      "name": "稳健纯债债券",     "risk_level": "C2", "category": "债券",
     "text": "纯债基金，以票息收益为主，波动很小，适合厌恶本金损失、只求稳稳收益的保守投资者。"},
    {"code": "P-SHORTBOND", "name": "短债30天持有",     "risk_level": "C3", "category": "债券",
     "text": "短期债券基金，收益略高于货币基金，最短持有30天，兼顾一定流动性与收益。"},
    {"code": "P-PENSION",   "name": "安心养老目标2040", "risk_level": "C3", "category": "养老",
     "text": "养老目标日期基金，长期持有，权益仓位随临近退休逐年下降，为退休储备而设计。"},
    {"code": "P-MIX",       "name": "灵活配置混合",     "risk_level": "C3", "category": "混合",
     "text": "股债灵活配置的混合基金，中等波动，攻守兼备，适合风险偏好适中的平衡型投资者。"},
    {"code": "P-GOLD",      "name": "黄金ETF联接",      "risk_level": "C4", "category": "另类",
     "text": "跟踪黄金价格，与股债相关性低，通胀上行或市场动荡时常作为避险与对冲配置。"},
    {"code": "P-TECH",      "name": "科技创新股票",     "risk_level": "C5", "category": "股票",
     "text": "股票型基金，重仓科技成长企业，波动大、回撤深，适合能承受大幅亏损、追求高收益的进取投资者。"},
]


# ---------- 可插拔 encoder（同 s4_01：文档 / query 分开，因为 e5 用不同前缀）----------
class Encoder(ABC):
    @abstractmethod
    def encode_docs(self, texts: list[str]) -> np.ndarray: ...
    @abstractmethod
    def encode_query(self, text: str) -> np.ndarray: ...


class EmbeddingEncoder(Encoder):
    """本地 multilingual-e5-small。e5 约定：文档加 'passage: '、query 加 'query: '。"""
    def __init__(self, model_name: str = "intfloat/multilingual-e5-small"):
        from sentence_transformers import SentenceTransformer
        print(f"[加载模型] {model_name} …（首次会下载权重）")
        self.model = SentenceTransformer(model_name)

    def encode_docs(self, texts: list[str]) -> np.ndarray:
        return self.model.encode([f"passage: {t}" for t in texts], normalize_embeddings=False)

    def encode_query(self, text: str) -> np.ndarray:
        return self.model.encode(f"query: {text}", normalize_embeddings=False)


# ========================= 向量库操作（★ 你来填）=========================
# 这三个函数就是「把 s4_01 的手搓检索换成 Chroma」的全部。注意对比：
#   s4_01: doc_vecs = list；retrieve_top_k 里 for 循环手算 cosine
#   这里 : collection 负责存 + 建索引 + 检索，你只管 add 和 query

def build_collection(client, encoder: Encoder, products: list[dict],
                     name: str = "finwise_products"):
    """把 products 向量化并写入一个 Chroma collection，返回该 collection。

    已给你：把 collection 建成 cosine 空间、把文档编码成向量。
    TODO#1：用 collection.upsert(...) 把数据写进去。要传四样东西（都是等长的 list）：
        ids        = 每条一个**唯一字符串**（用 product["code"]）
        embeddings = doc_vecs 对应的向量（Chroma 要 list，不吃 numpy → 用 .tolist()）
        documents  = 原始文本（product["text"]），检索时会原样返回
        metadatas  = [{"risk_level":..., "category":..., "name":...}, ...] 供过滤/展示
      提示：upsert 是「有则更新、无则插入」，比 add 更适合可重复跑（add 遇重复 id 会报错）。
    """
    # 建库：显式指定 cosine 空间（默认是 L2！文本检索要 cosine）
    collection = client.get_or_create_collection(
        name=name, metadata={"hnsw:space": "cosine"}
    )
    doc_vecs = encoder.encode_docs([p["text"] for p in products])  # (N, dim) numpy

    collection.upsert(
        ids=[p["code"] for p in products],
        embeddings=doc_vecs.tolist(),
        documents=[p["text"] for p in products],
        metadatas=[{"risk_level": p["risk_level"], "category": p["category"], "name": p["name"]} for p in products]
    )

    return collection


def search(collection, encoder: Encoder, query: str, k: int = 3) -> list[dict]:
    """语义检索 top-k，返回 [{code, name, distance}, ...]（distance 越小越相关）。

    TODO#2：
      1) 用 encoder.encode_query(query) 得到 query 向量（numpy → .tolist()）；
      2) 调 collection.query(query_embeddings=[<那个向量>], n_results=k)；
      3) 结果是个 dict，形如 {"ids":[[...]], "distances":[[...]], "metadatas":[[...]], ...}
         注意**每个值都是「list 套 list」**（外层按 query 分组，我们只有 1 条 query→取 [0]）；
      4) 组装成 [{"code": id, "name": meta["name"], "distance": dist}, ...] 返回。
    """
    query_vec = encoder.encode_query(query).tolist()
    results = collection.query(query_embeddings=[query_vec], n_results=k)
    return [{"code": id, "name": meta["name"], "distance": dist} for id, dist, meta in zip(results["ids"][0], results["distances"][0], results["metadatas"][0])]


def search_by_risk(collection, encoder: Encoder, query: str, risk_level: str,
                   k: int = 3) -> list[dict]:
    """「先按 risk_level 过滤，再语义检索」——这就是向量库相对手搓版的杀手锏。

    TODO#3：和 search 几乎一样，只多传一个过滤条件：
        collection.query(..., where={"risk_level": risk_level})
      Chroma 会**只在满足元数据条件的子集里**算相似度。返回格式同 search。
    """
    query_vec = encoder.encode_query(query).tolist()
    results = collection.query(
        query_embeddings=[query_vec],
        n_results=k,
        where={"risk_level": risk_level}
    )
    return [{"code": id, "name": meta["name"], "distance": dist} for id, dist, meta in zip(results["ids"][0], results["distances"][0], results["metadatas"][0])]


# =====================================================================


def _print_hits(title: str, hits: list[dict]) -> None:
    print(title)
    for h in hits:
        print(f"    dist={h['distance']:.3f}  {h['code']:12} {h['name']}")
    print()


def main() -> None:
    # 落盘目录（放系统临时区，不进 git）；PersistentClient = 数据会持久化到磁盘
    db_path = os.path.join(tempfile.gettempdir(), "finwise_chroma_demo")
    print(f"[Chroma 落盘路径] {db_path}\n")

    encoder = EmbeddingEncoder()
    client = chromadb.PersistentClient(path=db_path)

    # 1) 建库 + 写入
    col = build_collection(client, encoder, PRODUCTS)
    print(f"[已写入] {col.count()} 条产品向量\n")

    # 2) 纯语义检索（对标 s4_01）
    _print_hits("❓ 想要能随时取出来、基本不会亏的：", search(col, encoder, "想要能随时取出来、基本不会亏的"))

    # 3) 元数据过滤 + 语义检索（s4_01 做不到的）
    _print_hits("❓ [仅 C3] 攻守兼备、适中风险：",
                search_by_risk(col, encoder, "攻守兼备、适中风险", risk_level="C3"))

    # 4) 持久化：另开一个 client 指向同一路径，数据还在（无需重新编码写入）
    client2 = chromadb.PersistentClient(path=db_path)
    col2 = client2.get_collection("finwise_products")
    print(f"[持久化验证] 重新打开，产品数依旧 = {col2.count()}（进程重启也不丢）")


if __name__ == "__main__":
    main()

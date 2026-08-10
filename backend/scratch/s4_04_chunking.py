"""阶段四 · s4_04：chunking（分块）——长文档为什么要切块，切了检索好在哪

前面（s4_01）每个"文档"都很短（一句话卖点），一个向量就能代表。但真实文档往往是
**多主题长文**（一份产品说明书讲收益、风险、赎回、费率……）。回忆 concepts-basics
「文本长度→向量维度」：① 超 512 token 会被截断丢弃；② 就算没超，把多主题长文压成
**一个**向量 = 所有意思被平均成一团"糊"，检索时具体的点被稀释。

解法就是 **chunking**：把长文档切成小段，**每段单独 embedding**，每个向量代表一个
**聚焦**的片段。检索时能精准命中相关那一段，而不是拿"整篇平均"的糊向量去比。

本脚本做一个 A/B/C 三方对照（同一批长文档、同一 query、同一检索核心，只改"怎么切"）：
  - 方案 A「整篇」  ：每篇文档 → 1 个向量（不切）
  - 方案 B「按句/定长」：每句独立成块，超长句按 max_len 硬切（chunk_by_sentence）
  - 方案 C「贪心合并」：短句贪心攒进一块直到接近 max_len，绝不从句中截断（chunk_greedy）
观察两层：
  ① A vs (B/C)：切块能定位到「哪一段」、整篇只能到「哪篇」，且分块分数更高（整篇被多主题稀释）；
  ② B vs C：同样是切，"一句一块/硬切"会切出碎片、把一句话拦腰截断；"贪心合并"块更均匀、
     不切断语义单元——切法本身也影响检索质量。

★ 两个切法函数都在下面：B（chunk_by_sentence）已实现；C（chunk_greedy）是你的 TODO。

运行（纯本地，不需要 bridge）：
    cd backend && .venv/bin/python scratch/s4_04_chunking.py
"""
from __future__ import annotations

import numpy as np

from s4_01_rag_embedding import EmbeddingEncoder, retrieve_top_k


# ---- 语料：3 篇「多主题」长文档（每篇讲一个产品，内含 收益/风险/赎回/费率 等多个方面）----
DOCS: list[dict] = [
    {"code": "P-PENSION", "name": "安心养老目标2040", "text":
        "本产品为养老目标日期基金，服务于长期退休储备。"
        "收益方面，成立以来年化约百分之六，随权益仓位在临近2040年逐步下降，预期波动收敛。"
        "风险方面，中前期含较高权益仓位，短期可能出现两位数回撤，需长期持有以平滑波动。"
        "赎回方面，设有最短持有期一年，持有期内不可赎回，到期后按日常开放日办理。"
        "费用方面，管理费每年百分之零点八，申购费随金额分档、最高百分之一点二。"},
    {"code": "P-MMF", "name": "稳盈货币A", "text":
        "本产品为货币市场基金，主打流动性管理与活钱理财。"
        "收益方面，七日年化通常在百分之一点五到二点五之间，随市场资金面波动。"
        "风险方面，几乎无本金波动，属最低风险等级，适合应急备用金。"
        "赎回方面，支持快速赎回，单日额度内实时到账，无最短持有期限制。"
        "费用方面，无申购赎回费，仅计提较低的销售服务费。"},
    {"code": "P-TECH", "name": "科技创新股票", "text":
        "本产品为股票型基金，重仓人工智能、半导体等科技成长赛道。"
        "收益方面，历史波动极大，牛市年度回报可观、熊市可能大幅回撤，追求长期超额收益。"
        "风险方面，属最高风险等级，单日涨跌幅可达数个百分点，需承受较深回撤。"
        "赎回方面，无最短持有期，正常开放日可申赎，但建议长期持有以穿越周期。"
        "费用方面，管理费每年百分之一点五，申购费最高百分之一点五。"},
    # ★ 对抗性文档：故意放①一个远超 max_len(40) 的超长句 + ②一串极短句，
    #   用来让 B(定长硬切) 和 C(贪心合并) 切出明显不同的块：
    #   · 超长句 → B 从第 40 字硬切成两半（后半段"到期赎回…"成无头碎片）；C 整句保留。
    #   · 极短句串 → C 会把它们贪心攒进同一块；B 让它们各自成一块（很碎）。
    {"code": "P-QDII", "name": "环球配置QDII", "text":
        "本产品为跨境QDII基金，主要投资于境外成熟市场与新兴市场的股票债券及另类资产，"
        "通过全球分散配置以对冲单一市场风险并力争在不同经济周期中获取相对稳健的长期回报。"  # ← 与上句连成一个超长句(约60字)
        "起投一千元。"
        "按月开放。"
        "支持定投。"
        "费率从低。"},
]

# 查询：都是问某篇文档【某一个方面】的细节（不是整篇主旨）——考验能不能命中"那一段"
QUERIES = [
    "养老基金的赎回有什么限制？",       # 命中点：P-PENSION 的「赎回」那段（最短持有一年）
    "哪个产品能实时到账、随时取钱？",   # 命中点：P-MMF 的「赎回」那段（快速赎回实时到账）
    "科技基金的管理费是多少？",         # 命中点：P-TECH 的「费用」那段（管理费 1.5%）
    "有没有能全球分散、对冲单一市场风险的产品？",  # 命中点：QDII 的【超长句】——看 B 硬切碎片 vs C 完整
    "哪个产品起投门槛低、还支持定投？",           # 命中点：QDII 的【极短句串】——看 B 碎成多块 vs C 合并成一块
]


# ========================= 两种切法：B 已实现 / C 是你的 TODO =========================

def chunk_by_sentence(text: str, max_len: int = 40) -> list[str]:
    """方案 B（已实现）：每句独立成块；若某句超过 max_len，按 max_len 定长硬切。

    简单直接，但两个隐患：① 短句各自成块 → 块碎；② 定长硬切会把一句话拦腰截断，
    产生没头没尾的碎片。C 用贪心合并来规避这俩。
    """
    chunks = []
    for sent in text.split("。"):
        temp = sent.strip()
        chunks.extend([temp[i:i + max_len] for i in range(0, len(temp), max_len)])
    return chunks


def chunk_greedy(text: str, max_len: int = 40) -> list[str]:
    """TODO（方案 C）：按句切 + 贪心合并——句子是最小单位，绝不从句中截断。

      1) 用「。」切成句子，去掉空串（[s.strip() for ... if s.strip()]）；
      2) 维护"当前块" cur：依次看每个句子——
         · 若 cur 非空 且 加上这句会超过 max_len → 先把 cur 收进结果，再让 cur 从这句重新开始；
         · 否则把这句拼进 cur（拼接时可用「。」连回去，读起来更自然）；
      3) ★ 循环结束后，cur 里通常还剩最后一块，别忘了 append 进去（常见漏点）。
    返回块列表。对比 B：这里句子是原子，超长也只是"另起一块"，不会把句子切断。

    ---- 走查样例（max_len=40）----
    输入 text（一整段，句子用「。」分隔）：
        "本产品为养老目标日期基金，服务于长期退休储备。收益方面，成立以来年化约百分之六…。
         风险方面，中前期含较高权益仓位…。赎回方面，设有最短持有期一年…。费用方面，管理费…。"

    第 1 步 切句去空 → sentences（每个约 15~30 字）：
        ["本产品为养老目标日期基金，服务于长期退休储备",
         "收益方面，成立以来年化约百分之六，随权益仓位在临近2040年逐步下降，预期波动收敛",
         "风险方面，中前期含较高权益仓位，短期可能出现两位数回撤，需长期持有以平滑波动",
         "赎回方面，设有最短持有期一年，持有期内不可赎回，到期后按日常开放日办理",
         "费用方面，管理费每年百分之零点八，申购费随金额分档、最高百分之一点二"]

    第 2 步 贪心攒（cur 的演变；> 号表示"加上会超 40，先收掉再重开"）：
        句1(21字) → cur="本产品…储备"                （21 ≤ 40，放入）
        句2(31字) → 21+31=52 > 40 → 收掉块1，cur=句2   （块1="本产品…储备"）
        句3(30字) → 31+30=61 > 40 → 收掉块2，cur=句3   （块2=句2）
        …每句都较长，基本一句一块；若有两三个短句会被攒进同一块
        循环结束 → 别忘了把最后的 cur 收进结果

    输出 chunks（返回值）：
        ["本产品为养老目标日期基金，服务于长期退休储备",
         "收益方面，成立以来年化约百分之六，随权益仓位在临近2040年逐步下降，预期波动收敛",
         "风险方面…", "赎回方面，设有最短持有期一年…", "费用方面…"]
    对比 B：B 会把「收益方面…52字」这种长句从第 40 字硬切成两半（后半段成碎片）；
            C 因句子是原子，整句保留、只是不与下一句合并 → 无碎片。
    """
    sentences = [s.strip() for s in text.split("。") if s.strip()]
    chunks: list[str] = []
    cur: list[str] = []          # 攒句子用 list，最后 join——句号永远正确，不会出现 。。 或粘连
    for sent in sentences:
        cur_len = sum(len(s) for s in cur)
        if cur and cur_len + len(sent) > max_len:   # 当前块非空 且 加上这句会超长 → 先收掉
            chunks.append("。".join(cur) + "。")
            cur = [sent]
        else:
            cur.append(sent)
    if cur:                                          # 收尾：最后一块
        chunks.append("。".join(cur) + "。")
    return chunks

# =================================================================


def build_index_whole(encoder: EmbeddingEncoder) -> tuple[np.ndarray, list[dict]]:
    """方案 A「整篇」：每篇文档 → 1 个向量。返回 (向量矩阵, 元信息列表)。"""
    metas = [{"doc": d["name"], "text": d["text"]} for d in DOCS]
    vecs = encoder.encode_docs([m["text"] for m in metas])
    return np.asarray(vecs), metas


def build_index_chunked(encoder: EmbeddingEncoder, chunker) -> tuple[np.ndarray, list[dict]]:
    """通用分块索引：每篇文档 → 用传入的 chunker 切块 → 每块 1 个向量。"""
    metas: list[dict] = []
    for d in DOCS:
        for ch in chunker(d["text"]):
            metas.append({"doc": d["name"], "text": ch})
    vecs = encoder.encode_docs([m["text"] for m in metas])
    return np.asarray(vecs), metas


def main() -> None:
    encoder = EmbeddingEncoder()
    whole_vecs, whole_metas = build_index_whole(encoder)
    b_vecs, b_metas = build_index_chunked(encoder, chunk_by_sentence)
    c_vecs, c_metas = build_index_chunked(encoder, chunk_greedy)
    print(f"【A 整篇】{len(whole_metas)} 向量   "
          f"【B 按句/定长】{len(b_metas)} 向量   【C 贪心合并】{len(c_metas)} 向量\n")

    for q in QUERIES:
        qv = encoder.encode_query(q)
        print(f"❓ {q}")
        wi, ws = retrieve_top_k(qv, whole_vecs, k=1)[0]
        print(f"  A 整篇     → {whole_metas[wi]['doc']}（{ws:.3f}）  [只能定位到整篇]")
        bi, bs = retrieve_top_k(qv, b_vecs, k=1)[0]
        print(f"  B 按句/定长 → {b_metas[bi]['doc']}（{bs:.3f}）：{b_metas[bi]['text']}")
        ci, cs = retrieve_top_k(qv, c_vecs, k=1)[0]
        print(f"  C 贪心合并 → {c_metas[ci]['doc']}（{cs:.3f}）：{c_metas[ci]['text']}")
        print()


if __name__ == "__main__":
    main()

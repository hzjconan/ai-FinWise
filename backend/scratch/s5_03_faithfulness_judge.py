"""L02 · 第 8 步 · s5_03：忠实度评审（LLM-as-judge）+ 数字硬校验 + 校验评审本身

讲义：docs/ai-agent-learning/lessons/L02-rag-evaluation.md（第 4、5、8 步）

本脚本一次练三件事：
  ① LLM 评审：把回答拆成陈述，逐条判断资料里有没有依据 → Faithfulness / 幻觉率（第 4 步）
  ② 数字硬校验：用代码抽出回答里的数字，检查是否原样出现在资料里（第 4 步"关键字段用代码"）
  ③ eval 的 eval：每条样本都有【人工标注】，看评审和硬校验各自跟人工的一致程度（第 5 步）

为什么用"手工造好的回答"，不现场让 LLM 生成？
  —— 要校验评审，就得先知道标准答案。手工造的回答，哪条有幻觉是我们事先标好的（= 评审的 golden set）。
     现场生成的回答没有人工标注，就没法判断评审判得对不对。

⚠️ 已知局限：评审经 bridge 用 Claude；样本回答虽是手写的，但同一家族模型做评审仍可能有偏差（第 5 步"自我偏好"）。
   这里评的是"有没有依据"这类二元事实判断，影响相对小。样本只有 8 条，结论只能算方向。

前置：bridge 已启动（bash backend/scratch/run_bridge.sh）
运行：cd backend && .venv/bin/python scratch/s5_03_faithfulness_judge.py
测试：cd backend && .venv/bin/python -m pytest scratch/test_s5_03_faithfulness_judge.py -v
"""
from __future__ import annotations

import asyncio
import re

from _bridge import call_tool, make_client, section
from s4_01_rag_embedding import CORPUS
from s4_06_hybrid_rerank import _pad

PRODUCT = {d["code"]: f"{d['name']}：{d['text']}" for d in CORPUS}

# ---- 人工标注的样本：评审的 golden set ----
#   human_hallucinated = 人工判定这个回答里【有没有】至少一句无依据的话
SAMPLES: list[dict] = [
    {"id": "S1 正确",
     "question": "这笔钱可能随时要用，别让我亏本",
     "contexts": ["P-MMF"],
     "answer": "推荐稳盈货币A，它是货币市场基金，可以随时申购赎回，几乎没有波动，适合放应急备用金。",
     "human_hallucinated": False},
    {"id": "S2 编造数字",
     "question": "这笔钱可能随时要用，别让我亏本",
     "contexts": ["P-MMF"],
     "answer": "推荐稳盈货币A，它是货币市场基金，可以随时申购赎回，几乎没有波动，年化收益约2.5%，非常适合存放应急备用金。",
     "human_hallucinated": True},      # 2.5% 资料里没有
    {"id": "S3 张冠李戴",
     "question": "我年轻能扛，想搏一个翻倍的机会",
     "contexts": ["P-TECH", "P-MMF"],
     "answer": "推荐科技创新股票，它重仓科技成长企业，几乎没有波动，适合追求高收益的投资者。",
     "human_hallucinated": True},      # "几乎没有波动"是货币基金的特点，科技股写的是"波动大"
    {"id": "S4 夸大承诺",
     "question": "想给爸妈存养老钱，能放十年八年的",
     "contexts": ["P-PENSION"],
     "answer": "安心养老目标2040是养老目标日期基金，适合长期持有，能保证退休时收益稳定。",
     "human_hallucinated": True},      # "保证收益稳定"资料里没有；金融场景"保证"还是合规红线
    {"id": "S5 数字有依据",
     "question": "放几个月就要用，比余额宝强点就行",
     "contexts": ["P-SHORTBOND"],
     "answer": "短债30天持有是短期债券基金，收益比货币基金略高，最短要持有30天。",
     "human_hallucinated": False},     # 30 天资料里有
    {"id": "S6 正确拒答",
     "question": "有没有能贷款买房的产品？",
     "contexts": ["P-MMF", "P-BOND"],
     "answer": "目前的产品里没有和贷款买房相关的，暂无合适产品。",
     "human_hallucinated": False},
    {"id": "S7 编造比例",
     "question": "物价涨得凶，有没有保值抗跌的",
     "contexts": ["P-GOLD"],
     "answer": "黄金ETF联接跟踪黄金价格，和股债相关性低，建议拿出资产的10%左右做避险配置。",
     "human_hallucinated": True},      # 10% 资料里没有
    {"id": "S8 年份有依据",
     "question": "想给爸妈存养老钱，能放十年八年的",
     "contexts": ["P-PENSION"],
     "answer": "安心养老目标2040是养老目标日期基金，权益仓位会随着临近退休逐年下降。",
     "human_hallucinated": False},     # 2040 在产品名里
]


def build_context(codes: list[str]) -> str:
    return "\n".join(f"- {PRODUCT[c]}" for c in codes)


# ========================= TODO 8a：评审输出的 schema =========================
# 评审对每条陈述输出三个字段：claim（陈述原文）、reason（理由）、verdict（判定）。
# 🔁 第 5 步：字段顺序 = 生成顺序（05「schema 即 prompt」）——请按你认为对的顺序排好 properties。
#    verdict 只允许两个值："有依据" / "无依据"（用 enum 限定）。
CLAIM_ITEM_SCHEMA: dict = {
    "type": "object",
    "properties": {
        # TODO 8a：在这里写 claim / reason / verdict 三个字段，注意顺序
        "claim": {"type": "string"},
        "reason": {"type": "string"},
        "verdict": {"type": "string", "enum": ["有依据", "无依据"]},
    },
    "required": ["claim", "reason", "verdict"],
}

# =============================================================================

JUDGE_TOOL = {
    "name": "report_claims",
    "description": "把回答拆成陈述并逐条给出判定。",
    "input_schema": {
        "type": "object",
        "properties": {"claims": {"type": "array", "items": CLAIM_ITEM_SCHEMA}},
        "required": ["claims"],
    },
}


# ========================= TODO 8b：评审的 system prompt =========================
# 写给评审 LLM 的说明：它会在 user 消息里收到【资料】和【回答】。要让它：
#   - 把回答拆成一条条独立、可核对的事实陈述（推荐动作、客套话不算）
#   - 逐条判断：这条能不能从【资料】推出来？只看资料，不许用它自己的常识
#   - 想一想"夸大"怎么判（资料说"适合"、回答说"保证收益"）？金融场景要严还是松？
JUDGE_SYSTEM = """你是金融产品的合规评审员，任务是核对【回答】是否忠实于给定的【资料】。

第一步，把【回答】拆成一条条独立、可核对的事实陈述（claim）：
  - 一条陈述只讲一件事，同一事实的重复表述合并成一条。
  - 不拆推荐动作（"推荐XX""建议配置"）、客套话、过渡句，以及"暂无合适产品"这类没有事实内容的表述。

第二步，逐条判断这条陈述能不能【只凭资料】推出来：
  - "有依据"：资料里有对应文字支持，或可由资料直接推出（同义改写、近义表述算有依据）。
  - "无依据"：资料里找不到支持，或与资料矛盾（例如资料写"波动大"，回答却写"几乎没有波动"）。
  - 只能用【资料】判断，绝对不许用自己的常识、行业知识或任何外部信息补充。资料没说的，就是没依据。

第三步，金融场景从严把握：
  - 资料只说"适合""有助于"，回答升级成"保证""一定""稳赚""收益稳定"等承诺性表述，一律判"无依据"。
  - 数字、比例、期限、年份必须和资料里原样一致才算有依据；资料里没有的数字即为编造，判"无依据"。

输出要求：调用 report_claims 工具，claims 里的每条包含
  claim（陈述原文）、reason（一句话理由，指明资料里对应哪句，或说明资料缺什么）、verdict（只能是"有依据"或"无依据"）。
每条陈述都要先写 reason 再下 verdict，不要遗漏任何一条事实陈述。"""

# =============================================================================


async def judge(client, sample: dict) -> list[dict]:
    """调一次 LLM 评审，返回陈述列表 [{"claim", "reason", "verdict"}, ...]。"""
    user = f"【资料】\n{build_context(sample['contexts'])}\n\n【回答】\n{sample['answer']}"
    blocks = await call_tool(client, system=JUDGE_SYSTEM,
                             messages=[{"role": "user", "content": user}],
                             tools=[JUDGE_TOOL], max_tokens=1024, retries=2)
    for b in blocks:
        if b["name"] == "report_claims":
            return list(b["input"].get("claims", []))
    return []


# ========================= TODO 8c：从评审结果算分 =========================

def score(claims: list[dict]) -> tuple[float, bool]:
    """TODO 8c：返回 (faithfulness, hallucinated)。

      faithfulness = 判定为"有依据"的陈述数 ÷ 全部陈述数        （第 4 步）
      hallucinated = 是否【至少有一条】判定为"无依据"            （幻觉率按回答统计）
    边界：claims 为空（比如正确拒答，没有事实陈述）→ 没有东西可核对，返回 (1.0, False)。
    """
    if not claims:                      # 没有事实陈述可核对（如正确拒答）→ 不算幻觉
        return 1.0, False
    supported = sum(1 for c in claims if c.get("verdict") == "有依据")
    return supported / len(claims), supported < len(claims)

# =========================================================================


# ========================= TODO 8d：数字硬校验 =========================

def unsupported_numbers(answer: str, context: str) -> list[str]:
    """TODO 8d：返回回答里出现、但资料里【没有原样出现】的数字（按在回答中出现的顺序）。

    "数字"指连续的数字串，可以带小数点：如 "2.5"、"30"、"2040"、"10"。
    提示：re.findall(r"\\d+(?:\\.\\d+)?", text) 能抽出所有数字串；
         判断"在不在资料里"可以直接用 `数字 in context`（简单版，够用）。
    例：answer="年化约2.5%，持有30天"，context="最短持有30天" → ["2.5"]
    """
    context_numbers = set(re.findall(r"\d+(?:\.\d+)?", context))
    return [n for n in re.findall(r"\d+(?:\.\d+)?", answer) if n not in context_numbers]

# ======================================================================


async def main() -> None:
    client = make_client()
    rows = []
    section("逐条样本：评审拆出的陈述")
    for s in SAMPLES:
        claims = await judge(client, s)
        faith, judge_h = score(claims)
        nums = unsupported_numbers(s["answer"], build_context(s["contexts"]))
        rows.append((s, faith, judge_h, bool(nums), nums))
        print(f"\n【{s['id']}】{s['answer']}")
        for c in claims:
            mark = "✅" if c.get("verdict") == "有依据" else "❌"
            print(f"   {mark} {c.get('claim')}  —— {c.get('reason')}")

    section("汇总（人工标注 = 标准答案）")
    print(_pad("样本", 16) + _pad("人工", 8) + _pad("评审", 8) + _pad("Faith", 8) + "数字硬校验")
    for s, faith, judge_h, num_h, nums in rows:
        yn = lambda b: "有幻觉" if b else "无"
        print(_pad(s["id"], 16) + _pad(yn(s["human_hallucinated"]), 8) + _pad(yn(judge_h), 8)
              + _pad(f"{faith:.2f}", 8) + (f"有幻觉 {nums}" if num_h else "无"))

    n = len(rows)
    truth = [s["human_hallucinated"] for s, *_ in rows]
    for name, preds in [("LLM 评审", [r[2] for r in rows]), ("数字硬校验", [r[3] for r in rows])]:
        agree = sum(p == t for p, t in zip(preds, truth))
        caught = sum(p and t for p, t in zip(preds, truth))
        print(f"\n{name}：与人工一致 {agree}/{n}；幻觉抓到 {caught}/{sum(truth)}；"
              f"幻觉率 {sum(preds)}/{n}（人工 {sum(truth)}/{n}）")


if __name__ == "__main__":
    asyncio.run(main())

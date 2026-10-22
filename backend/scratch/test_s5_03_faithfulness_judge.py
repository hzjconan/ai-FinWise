"""s5_03 配套测试：不调 LLM，只测 schema 顺序、prompt 已填、算分和数字硬校验。

    cd backend && .venv/bin/python -m pytest scratch/test_s5_03_faithfulness_judge.py -v
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import s5_03_faithfulness_judge as m  # noqa: E402


# ---------- 8a：schema ----------

def test_claim_schema_has_three_fields():
    assert set(m.CLAIM_ITEM_SCHEMA["properties"]) == {"claim", "reason", "verdict"}


def test_claim_schema_reason_before_verdict():
    # 第 5 步：理由在前、判定在后（properties 顺序 = 生成顺序）
    keys = list(m.CLAIM_ITEM_SCHEMA["properties"])
    assert keys.index("reason") < keys.index("verdict")


def test_verdict_limited_to_two_values():
    assert set(m.CLAIM_ITEM_SCHEMA["properties"]["verdict"]["enum"]) == {"有依据", "无依据"}


# ---------- 8b：prompt ----------

def test_judge_prompt_is_filled_in():
    assert "TODO" not in m.JUDGE_SYSTEM and len(m.JUDGE_SYSTEM.strip()) > 30


# ---------- 8c：score ----------

def _c(*verdicts):
    return [{"claim": f"c{i}", "reason": "r", "verdict": v} for i, v in enumerate(verdicts)]


def test_score_lesson_example():
    # 第 4 步：5 条里 1 条无依据 → 0.8，且算有幻觉
    faith, h = m.score(_c("有依据", "有依据", "有依据", "无依据", "有依据"))
    assert faith == pytest.approx(0.8)
    assert h is True


def test_score_all_supported():
    assert m.score(_c("有依据", "有依据")) == (1.0, False)


def test_score_empty_claims_means_nothing_to_check():
    assert m.score([]) == (1.0, False)


# ---------- 8d：unsupported_numbers ----------

def test_numbers_finds_fabricated_decimal():
    assert m.unsupported_numbers("年化约2.5%，持有30天", "最短持有30天") == ["2.5"]


def test_numbers_supported_by_product_name():
    assert m.unsupported_numbers("安心养老目标2040很稳", "安心养老目标2040：养老目标日期基金") == []


def test_numbers_keeps_answer_order():
    assert m.unsupported_numbers("拿出10%，持有3年", "无数字") == ["10", "3"]


def test_numbers_none_in_answer():
    assert m.unsupported_numbers("几乎没有波动", "几乎无波动") == []


def test_numbers_not_fooled_by_substring():
    # "3" 是 "30" 的子串，但不是同一个数字 → 必须判为无依据
    assert m.unsupported_numbers("最短持有3天就能取出来", "最短持有30天，兼顾一定流动性") == ["3"]
    # "5" 是 "2.5" 的一部分，"20" 是 "2040" 的一部分
    assert m.unsupported_numbers("年化5%，目标20年", "年化2.5%，目标2040") == ["5", "20"]

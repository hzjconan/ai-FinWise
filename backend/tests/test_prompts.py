"""风险评估 prompt / 维度加载测试。"""
from app.services.llm.prompts import load_dimensions, load_system_prompt


def test_load_dimensions_returns_five():
    dims = load_dimensions()
    assert len(dims) == 5
    keys = {d["key"] for d in dims}
    assert keys == {
        "experience",
        "loss_tolerance",
        "income_stability",
        "investment_horizon",
        "volatility_tolerance",
    }


def test_each_dimension_has_1_to_5_anchors():
    for d in load_dimensions():
        assert set(d["anchors"].keys()) == {1, 2, 3, 4, 5}, d["key"]
        for score, text in d["anchors"].items():
            assert isinstance(text, str) and text.strip(), (d["key"], score)


def test_load_system_prompt_contains_all_dimensions_and_tool_rules():
    prompt = load_system_prompt()
    # 角色与工具约束
    assert "风险评估助手" in prompt
    assert "ask_next_question" in prompt
    assert "conclude_assessment" in prompt
    # 所有维度名都渲染进来
    for d in load_dimensions():
        assert d["name"] in prompt
        assert d["key"] in prompt
    # 占位符必须被替换
    assert "{DIMENSIONS}" not in prompt

from claude_cli_bridge.prompt_builder import build_prompt

ASK_TOOL = {
    "name": "ask_next_question",
    "description": "继续提问",
    "input_schema": {
        "type": "object",
        "properties": {"content": {"type": "string"}},
        "required": ["content"],
    },
}
CONCLUDE_TOOL = {
    "name": "conclude_assessment",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}


def test_includes_system_tools_and_messages():
    out = build_prompt(
        system="你是助手",
        messages=[{"role": "user", "content": "我想了解风险评估"}],
        tools=[ASK_TOOL, CONCLUDE_TOOL],
    )
    assert "你是助手" in out
    assert "ask_next_question" in out
    assert "conclude_assessment" in out
    assert "我想了解风险评估" in out
    assert out.rstrip().endswith("Assistant:")


def test_empty_messages_marks_first_round():
    out = build_prompt(system="sys", messages=[], tools=[ASK_TOOL])
    assert "第一轮" in out or "开场白" in out


def test_assistant_tool_use_history_rendered_as_json():
    history = [
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "name": "ask_next_question", "input": {"content": "Q1"}},
            ],
        },
        {"role": "user", "content": "我答 A1"},
    ]
    out = build_prompt(system="", messages=history, tools=[ASK_TOOL])
    assert "ask_next_question" in out
    assert "Q1" in out
    assert "A1" in out


def test_tools_block_emphasizes_pure_json_output():
    out = build_prompt(system="", messages=[], tools=[ASK_TOOL])
    assert "tool_name" in out
    assert "tool_input" in out
    # 关键约束：禁止围栏 / markdown
    assert "禁止" in out

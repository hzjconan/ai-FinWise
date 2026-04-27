import pytest

from claude_cli_bridge.tool_parser import ToolParseError, parse_tool_call

ALLOWED = ["ask_next_question", "conclude_assessment"]


def test_pure_json():
    raw = '{"tool_name":"ask_next_question","tool_input":{"content":"hi"}}'
    name, inp = parse_tool_call(raw, ALLOWED)
    assert name == "ask_next_question"
    assert inp == {"content": "hi"}


def test_fenced_json():
    raw = '```json\n{"tool_name":"ask_next_question","tool_input":{"content":"hi"}}\n```'
    name, inp = parse_tool_call(raw, ALLOWED)
    assert name == "ask_next_question"
    assert inp == {"content": "hi"}


def test_json_with_surrounding_text():
    raw = (
        '我的回答是：\n'
        '{"tool_name":"conclude_assessment",'
        '"tool_input":{"content":"完成","risk_preference":"C3","summary":"...","dimensions":{}}}'
        '\n以上。'
    )
    name, inp = parse_tool_call(raw, ALLOWED)
    assert name == "conclude_assessment"
    assert inp["risk_preference"] == "C3"


def test_nested_braces_handled():
    raw = (
        '{"tool_name":"conclude_assessment",'
        '"tool_input":{"content":"x","risk_preference":"C3","summary":"s",'
        '"dimensions":{"experience":3,"loss_tolerance":4}}}'
    )
    name, inp = parse_tool_call(raw, ALLOWED)
    assert inp["dimensions"]["loss_tolerance"] == 4


def test_unknown_tool_name_raises():
    raw = '{"tool_name":"hack","tool_input":{}}'
    with pytest.raises(ToolParseError, match="未知 tool_name"):
        parse_tool_call(raw, ALLOWED)


def test_missing_fields_raises():
    raw = '{"tool":"x"}'
    with pytest.raises(ToolParseError):
        parse_tool_call(raw, ALLOWED)


def test_empty_raises():
    with pytest.raises(ToolParseError, match="为空"):
        parse_tool_call("   ", ALLOWED)


def test_no_json_raises():
    with pytest.raises(ToolParseError, match="JSON"):
        parse_tool_call("just plain text without braces", ALLOWED)


def test_string_with_braces_in_quote_does_not_break_balance():
    raw = '{"tool_name":"ask_next_question","tool_input":{"content":"用 } 试试"}}'
    name, inp = parse_tool_call(raw, ALLOWED)
    assert inp == {"content": "用 } 试试"}

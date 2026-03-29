"""Tests for prompts.py — build_system_prompt context injection paths."""
import importlib
import pytest


def test_tool_descriptions_present():
    from prompts import build_system_prompt
    prompt = build_system_prompt()
    assert "web_search" in prompt
    assert "update_note" in prompt
    assert "recall" in prompt


def test_memory_context_injected():
    from prompts import build_system_prompt
    prompt = build_system_prompt(memory_context="tokio is async rust")
    assert "tokio is async rust" in prompt
    assert "Context From Previous Sessions" in prompt


def test_memory_context_omitted_when_empty():
    from prompts import build_system_prompt
    prompt = build_system_prompt(memory_context="")
    assert "Context From Previous Sessions" not in prompt


def test_topic_context_injected():
    from prompts import build_system_prompt
    prompt = build_system_prompt(topic_context="Research: AI Safety")
    assert "Research: AI Safety" in prompt
    assert "Current Research Task" in prompt


def test_static_context_injected(tmp_path, monkeypatch):
    """Non-empty context.md → ## Agent Context section appears in prompt."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "context.md").write_text("## Research Goals\nFocus on AI.", encoding="utf-8")

    import context as ctx_module
    importlib.reload(ctx_module)
    ctx_module.load_context()

    import prompts
    importlib.reload(prompts)

    prompt = prompts.build_system_prompt()
    assert "## Agent Context" in prompt
    assert "Focus on AI" in prompt


def test_static_context_absent_when_empty(tmp_path, monkeypatch):
    """Empty context.md → ## Agent Context NOT in prompt."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "context.md").write_text("", encoding="utf-8")

    import context as ctx_module
    importlib.reload(ctx_module)
    ctx_module.load_context()

    import prompts
    importlib.reload(prompts)

    prompt = prompts.build_system_prompt()
    assert "## Agent Context" not in prompt


def test_parse_tool_call_json_block():
    from prompts import parse_tool_call
    text = '```json\n{"tool": "web_search", "query": "test"}\n```'
    result = parse_tool_call(text)
    assert result is not None
    assert result["tool"] == "web_search"
    assert result["query"] == "test"


def test_parse_tool_call_bare_json():
    from prompts import parse_tool_call
    text = 'Thinking... {"tool": "recall", "query": "python"} done.'
    result = parse_tool_call(text)
    assert result is not None
    assert result["tool"] == "recall"


def test_parse_tool_call_no_tool():
    from prompts import parse_tool_call
    result = parse_tool_call("Here is my final answer with no tool call.")
    assert result is None


def test_parse_tool_call_trailing_comma():
    from prompts import parse_tool_call
    text = '```json\n{"tool": "web_search", "query": "test",}\n```'
    result = parse_tool_call(text)
    assert result is not None
    assert result["tool"] == "web_search"

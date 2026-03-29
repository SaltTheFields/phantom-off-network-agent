"""Tests for context.py — static context file load/cache/reload."""
import os
import importlib
import pytest


def _fresh_context_module():
    """Re-import context module with clean cache state."""
    import context
    importlib.reload(context)
    return context


def test_creates_default_file(tmp_path, monkeypatch):
    """Missing context.md → auto-created with default template."""
    monkeypatch.chdir(tmp_path)
    ctx = _fresh_context_module()
    content = ctx.load_context()
    assert os.path.exists(tmp_path / "context.md")
    assert "## Research Goals" in content
    assert "## Global Rules" in content


def test_get_returns_cached(tmp_path, monkeypatch):
    """get_context() called twice — file read only once (cache hit)."""
    monkeypatch.chdir(tmp_path)
    ctx = _fresh_context_module()
    ctx.load_context()
    first = ctx.get_context()
    # Overwrite the file; get_context should still return the cached version
    (tmp_path / "context.md").write_text("CHANGED", encoding="utf-8")
    second = ctx.get_context()
    assert first == second
    assert "CHANGED" not in second


def test_reload_picks_up_edits(tmp_path, monkeypatch):
    """Edit file → reload_context() → new content returned."""
    monkeypatch.chdir(tmp_path)
    ctx = _fresh_context_module()
    ctx.load_context()
    (tmp_path / "context.md").write_text("## Updated Goals\nFocus on robotics.", encoding="utf-8")
    new_content = ctx.reload_context()
    assert "robotics" in new_content
    assert ctx.get_context() == new_content


def test_empty_file_returns_empty_string(tmp_path, monkeypatch):
    """Blank context.md → empty string, no section injected."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "context.md").write_text("", encoding="utf-8")
    ctx = _fresh_context_module()
    content = ctx.load_context()
    assert content == ""
    # Verify build_system_prompt doesn't inject a section for empty context
    import prompts
    prompt = prompts.build_system_prompt()
    assert "## Agent Context" not in prompt

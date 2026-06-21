"""Tests für die erweiterten Features: agentic parser, tools, usage, plugins."""

import tempfile
from pathlib import Path

from nexoryx.orchestrator.orchestrator import Orchestrator
from nexoryx.tools.base import Tool, ToolContext, ToolResult
from nexoryx.tools.code import GlobTool, GrepTool
from nexoryx.tools.registry import get_tool, register


def test_agentic_parser_json_and_soft():
    assert Orchestrator._parse_action('ACTION: web_search {"query": "x"}') == ("web_search", {"query": "x"})
    assert Orchestrator._parse_action("ACTION: terminal ls -la") == ("terminal", {"command": "ls -la"})
    assert Orchestrator._parse_action("FINAL: done") is None


def test_glob_and_grep():
    with tempfile.TemporaryDirectory() as root:
        (Path(root) / "a.py").write_text("def foo():\n    return 1\n")
        ctx = ToolContext(role="user", project_root=root)
        assert "a.py" in GlobTool().run({"pattern": "**/*.py"}, ctx).output
        assert "def foo" in GrepTool().run({"pattern": "def foo"}, ctx).output


def test_plugin_register():
    class PingTool(Tool):
        name = "ping_test"
        description = "test"
        permission = "auto"

        def run(self, args, ctx):
            return ToolResult(True, "pong")

    register(PingTool())
    assert get_tool("ping_test") is not None


def test_usage_over_budget(monkeypatch=None):
    from nexoryx.platform import usage
    # over_budget(0) ist immer False (unbegrenzt)
    assert usage.over_budget(0.0) is False

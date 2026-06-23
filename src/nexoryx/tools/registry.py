"""Tool-Registry + zentraler, geprüfter Ausführungs-Pfad.

`run_tool` setzt die Defense-in-Depth-Kette durch: Permission → (confirm-Gate) →
Sandbox/Tool → Audit. Security-Veto/Approve passiert über `confirm`.
"""

from __future__ import annotations

from typing import Callable

from .audit import audit
from .base import Tool, ToolContext, ToolResult
from .code import GitTool, GlobTool, GrepTool
from .browser import (
    BrowserNavigateTool, BrowserScreenshotTool, BrowserClickTool,
    BrowserFillTool, BrowserExtractTool,
)
from .computer import (
    KeyPressTool, MouseClickTool, MouseMoveTool, ScreenshotTool, ScrollTool, TypeTextTool,
)
from .filesystem import FileReadTool, FileWriteTool
from .permissions import check_permission
from .terminal import TerminalTool
from .web import HttpFetchTool, WebSearchTool

_TOOLS: dict[str, Tool] = {
    t.name: t for t in (
        TerminalTool(), FileReadTool(), FileWriteTool(),
        HttpFetchTool(), WebSearchTool(), GlobTool(), GrepTool(), GitTool(),
        ScreenshotTool(), MouseClickTool(), MouseMoveTool(),
        TypeTextTool(), KeyPressTool(), ScrollTool(),
        BrowserNavigateTool(), BrowserScreenshotTool(), BrowserClickTool(),
        BrowserFillTool(), BrowserExtractTool(),
    )
}


def register(tool: Tool) -> None:
    """Tool registrieren (für Plugins)."""
    _TOOLS[tool.name] = tool


def load_plugins() -> list[str]:
    """Tools aus ~/.nexoryx/plugins/*.py laden.

    Ein Plugin definiert Tool-Subklassen und eine Funktion `register(reg)`,
    die `reg(MyTool())` aufruft. Gibt die Liste geladener Plugin-Dateien zurück.
    """
    import importlib.util
    from ..platform.config import CONFIG_DIR

    plugin_dir = CONFIG_DIR / "plugins"
    loaded: list[str] = []
    if not plugin_dir.is_dir():
        return loaded
    for path in sorted(plugin_dir.glob("*.py")):
        try:
            spec = importlib.util.spec_from_file_location(f"nx_plugin_{path.stem}", path)
            if not spec or not spec.loader:
                continue
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if hasattr(mod, "register"):
                mod.register(register)
                loaded.append(path.name)
        except Exception:  # ein kaputtes Plugin darf nicht den Start verhindern
            continue
    return loaded


def list_tools() -> list[Tool]:
    return list(_TOOLS.values())


def get_tool(name: str) -> Tool | None:
    return _TOOLS.get(name)


def run_tool(name: str, args: dict, ctx: ToolContext,
             confirm_cb: Callable[[Tool, str], bool] | None = None) -> ToolResult:
    tool = _TOOLS.get(name)
    if tool is None:
        return ToolResult(False, "", f"Unbekanntes Tool: {name}")

    decision = check_permission(tool, ctx)
    if decision.verdict == "deny":
        audit("tool.denied", tool=name, actor=ctx.actor, role=ctx.role, reason=decision.reason)
        return ToolResult(False, "", f"Verweigert: {decision.reason}")

    if decision.verdict == "confirm":
        approved = confirm_cb(tool, decision.reason) if confirm_cb else False
        if not approved:
            audit("tool.refused", tool=name, actor=ctx.actor, args=args)
            return ToolResult(False, "", "Aktion nicht bestätigt (Approve/Deny)")

    result = tool.run(args, ctx)
    audit("tool.run", tool=name, actor=ctx.actor, role=ctx.role,
          ok=result.ok, args=args, meta=result.meta,
          error=result.error[:200] if result.error else "")
    return result

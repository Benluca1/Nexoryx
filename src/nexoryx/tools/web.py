"""Web-Tools: HTTP-Fetch + Web-Suche (zero-dependency, urllib).

web_search nutzt das HTML-Endpoint von DuckDuckGo (kein API-Key nötig).
Beides read-only → Permission `auto`.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request

from .base import Tool, ToolContext, ToolResult

_UA = {"User-Agent": "Mozilla/5.0 (Nexoryx)"}
_TAG = re.compile(r"<[^>]+>")
_RESULT = re.compile(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.S)


def _strip(html: str) -> str:
    text = _TAG.sub(" ", html)
    return re.sub(r"\s+", " ", text).strip()


class HttpFetchTool(Tool):
    name = "http_fetch"
    description = "Holt den Textinhalt einer URL (GET)."
    permission = "auto"
    schema = {"url": "string"}

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        url = (args.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            return ToolResult(False, "", "Ungültige URL")
        try:
            req = urllib.request.Request(url, headers=_UA)
            with urllib.request.urlopen(req, timeout=20) as r:
                raw = r.read(500_000).decode("utf-8", errors="replace")
        except (urllib.error.URLError, OSError) as exc:
            return ToolResult(False, "", str(exc))
        return ToolResult(True, _strip(raw)[:12_000])


class WebSearchTool(Tool):
    name = "web_search"
    description = "Sucht im Web (DuckDuckGo) und gibt Titel + URLs zurück."
    permission = "auto"
    schema = {"query": "string"}

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        query = (args.get("query") or "").strip()
        if not query:
            return ToolResult(False, "", "Leere Suchanfrage")
        url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
        try:
            req = urllib.request.Request(url, headers=_UA)
            with urllib.request.urlopen(req, timeout=20) as r:
                html = r.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, OSError) as exc:
            return ToolResult(False, "", str(exc))
        results = []
        for href, title in _RESULT.findall(html)[:8]:
            results.append(f"- {_strip(title)} — {href}")
        return ToolResult(True, "\n".join(results) or "(keine Treffer)")

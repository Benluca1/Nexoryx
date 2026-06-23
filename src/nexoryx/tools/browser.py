"""Browser-Tool — Playwright-basierte Chromium-Steuerung.

Nutzt den bereits vorhandenen Chromium-Build in ~/.cache/ms-playwright/
(wird bei der Installation automatisch gefunden, kein Download nötig).

Headless-Standard; headful nur wenn DISPLAY gesetzt und explizit angefordert.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

from .base import Tool, ToolContext, ToolResult

# Chromium-Pfad: vorhandenen Build automatisch finden
def _chromium_exe() -> str | None:
    cache = Path.home() / ".cache" / "ms-playwright"
    if not cache.exists():
        return None
    for d in sorted(cache.glob("chromium-*/chrome-linux*/chrome"), reverse=True):
        if d.exists():
            return str(d)
    for d in sorted(cache.glob("chromium-*/chrome-linux64/chrome"), reverse=True):
        if d.exists():
            return str(d)
    return None


def _launch(headless: bool = True):
    """Playwright-Browser starten. Gibt (playwright_ctx, browser, page) zurück."""
    from playwright.sync_api import sync_playwright
    exe = _chromium_exe()
    pw = sync_playwright().start()
    launch_opts = {"headless": headless}
    if exe:
        launch_opts["executable_path"] = exe
    browser = pw.chromium.launch(**launch_opts)
    page = browser.new_page()
    page.set_default_timeout(20_000)
    return pw, browser, page


class BrowserNavigateTool(Tool):
    name = "browser_navigate"
    description = (
        "Öffnet eine URL im Headless-Browser und gibt Titel + Text-Inhalt zurück. "
        "Ideal um Webseiten zu lesen, Informationen zu extrahieren oder Login-Seiten aufzurufen."
    )
    permission = "auto"
    schema = {"url": "string", "wait_for": "string?"}

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        url = args.get("url", "").strip()
        if not url:
            return ToolResult(False, "", "Keine URL angegeben")
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        try:
            pw, browser, page = _launch()
            try:
                page.goto(url, wait_until="domcontentloaded")
                wait_sel = args.get("wait_for")
                if wait_sel:
                    page.wait_for_selector(wait_sel, timeout=8000)
                title = page.title()
                # Text-Inhalt extrahieren (body, ohne Scripts/Styles)
                text = page.evaluate("""() => {
                    const el = document.body;
                    if (!el) return '';
                    const clone = el.cloneNode(true);
                    clone.querySelectorAll('script,style,noscript,svg').forEach(e => e.remove());
                    return clone.innerText || clone.textContent || '';
                }""")
                text = " ".join(text.split())[:4000]
                current_url = page.url
                return ToolResult(
                    ok=True,
                    output=f"[{title}] {current_url}\n\n{text}",
                    meta={"title": title, "url": current_url},
                )
            finally:
                browser.close()
                pw.stop()
        except Exception as e:
            return ToolResult(False, "", f"Browser-Fehler: {e}")


class BrowserScreenshotTool(Tool):
    name = "browser_screenshot"
    description = "Macht einen Screenshot einer Webseite (headless). Gibt Pfad zur PNG-Datei zurück."
    permission = "auto"
    schema = {"url": "string", "full_page": "bool?"}

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        url = args.get("url", "").strip()
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        try:
            import tempfile
            pw, browser, page = _launch()
            try:
                page.goto(url, wait_until="domcontentloaded")
                tmp = tempfile.mktemp(suffix=".png", prefix="nex_web_")
                page.screenshot(path=tmp, full_page=bool(args.get("full_page", False)))
                size_kb = Path(tmp).stat().st_size // 1024
                return ToolResult(
                    ok=True,
                    output=f"Screenshot: {tmp}  ({size_kb} KB)\nURL: {page.url}",
                    meta={"path": tmp, "url": page.url, "size_kb": size_kb},
                )
            finally:
                browser.close()
                pw.stop()
        except Exception as e:
            return ToolResult(False, "", f"Screenshot-Fehler: {e}")


class BrowserClickTool(Tool):
    name = "browser_click"
    description = (
        "Klickt auf ein Element in der aktuell offenen Browserseite per CSS-Selektor. "
        "Muss nach browser_navigate verwendet werden — öffnet keine neue URL."
    )
    permission = "confirm"
    schema = {"url": "string", "selector": "string", "text_after": "bool?"}

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        url = args.get("url", "").strip()
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        selector = args.get("selector", "")
        if not selector:
            return ToolResult(False, "", "Kein CSS-Selektor angegeben")
        try:
            pw, browser, page = _launch()
            try:
                page.goto(url, wait_until="domcontentloaded")
                page.click(selector)
                page.wait_for_load_state("domcontentloaded")
                result = f"Klick auf '{selector}' — neue URL: {page.url}"
                if args.get("text_after"):
                    text = page.evaluate("() => document.body.innerText")
                    result += "\n\n" + " ".join(text.split())[:2000]
                return ToolResult(ok=True, output=result, meta={"url": page.url})
            finally:
                browser.close()
                pw.stop()
        except Exception as e:
            return ToolResult(False, "", f"Klick-Fehler: {e}")


class BrowserFillTool(Tool):
    name = "browser_fill"
    description = (
        "Füllt ein Formularfeld aus und sendet es optional ab (submit=true). "
        "Beispiel: Login-Felder befüllen."
    )
    permission = "confirm"
    schema = {"url": "string", "selector": "string", "value": "string", "submit": "bool?"}

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        url = args.get("url", "").strip()
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        selector = args.get("selector", "")
        value = args.get("value", "")
        try:
            pw, browser, page = _launch()
            try:
                page.goto(url, wait_until="domcontentloaded")
                page.fill(selector, value)
                if args.get("submit"):
                    page.keyboard.press("Enter")
                    page.wait_for_load_state("domcontentloaded")
                return ToolResult(
                    ok=True,
                    output=f"Feld '{selector}' befüllt mit {repr(value)[:40]}. URL: {page.url}",
                    meta={"url": page.url},
                )
            finally:
                browser.close()
                pw.stop()
        except Exception as e:
            return ToolResult(False, "", f"Formular-Fehler: {e}")


class BrowserExtractTool(Tool):
    name = "browser_extract"
    description = (
        "Extrahiert Daten aus einer Webseite per CSS-Selektor. "
        "Gibt Text aller passenden Elemente zurück. "
        "Nützlich für Listen, Tabellen, strukturierte Inhalte."
    )
    permission = "auto"
    schema = {"url": "string", "selector": "string", "limit": "int?"}

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        url = args.get("url", "").strip()
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        selector = args.get("selector", "body")
        limit = int(args.get("limit", 20))
        try:
            pw, browser, page = _launch()
            try:
                page.goto(url, wait_until="domcontentloaded")
                elements = page.query_selector_all(selector)[:limit]
                items = [el.inner_text().strip() for el in elements if el.inner_text().strip()]
                output = f"{len(items)} Elemente für '{selector}':\n" + "\n".join(
                    f"  {i+1}. {t[:200]}" for i, t in enumerate(items)
                )
                return ToolResult(ok=True, output=output, meta={"count": len(items)})
            finally:
                browser.close()
                pw.stop()
        except Exception as e:
            return ToolResult(False, "", f"Extraktion-Fehler: {e}")

"""Nexoryx Desktop-GUI — pywebview-Fenster mit Daemon-Auto-Start und JS-Bridge."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

_STATIC = Path(__file__).parent / "static"
_DAEMON_HOST = "http://127.0.0.1:3008"


# ── Daemon-Verwaltung ──────────────────────────────────────────────────────────

class _DaemonManager:
    def is_alive(self) -> bool:
        try:
            urllib.request.urlopen(f"{_DAEMON_HOST}/health", timeout=2)
            return True
        except Exception:
            return False

    def start(self) -> None:
        log_path = Path.home() / ".nexoryx" / "daemon.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.Popen(
            [sys.executable, "-m", "nexoryx", "daemon"],
            start_new_session=True,
            stdout=open(log_path, "a"),
            stderr=subprocess.STDOUT,
        )
        pid_file = Path.home() / ".nexoryx" / "nexoryxd.pid"
        pid_file.write_text(str(proc.pid))

    def wait_ready(self, timeout: float = 20.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.is_alive():
                return True
            time.sleep(0.5)
        return False

    def fetch_json(self, path: str) -> dict:
        with urllib.request.urlopen(f"{_DAEMON_HOST}{path}", timeout=5) as r:
            return json.loads(r.read())


# ── JS-Bridge (alle public-Methoden sind aus JS aufrufbar) ────────────────────

class NexoryxAPI:
    def __init__(self, daemon: _DaemonManager) -> None:
        self._daemon = daemon
        self._hw = None
        self._profile = None
        self.window = None  # wird nach create_window() gesetzt

    # -- Daemon ----------------------------------------------------------------

    def check_daemon(self) -> dict:
        if self._daemon.is_alive():
            return {"running": True, "started": False}
        self._daemon.start()
        ready = self._daemon.wait_ready()
        return {"running": ready, "started": True}

    # -- Status ----------------------------------------------------------------

    def get_status(self) -> dict:
        try:
            return self._daemon.fetch_json("/status")
        except Exception as exc:
            return {"error": str(exc)}

    def get_training_status(self) -> dict:
        try:
            return self._daemon.fetch_json("/training/status")
        except Exception as exc:
            return {"error": str(exc)}

    # -- Chat / Streaming ------------------------------------------------------

    def start_ask(self, prompt: str) -> None:
        """Kehrt sofort zurück; liefert Tokens über evaluate_js."""
        threading.Thread(target=self._stream_ask, args=(prompt,), daemon=True).start()

    def _stream_ask(self, prompt: str) -> None:
        if self.window is None:
            return
        try:
            self._ensure_hw()
            from ...router import Router, ChatRequest
            router = Router(self._hw, self._profile)
            req = ChatRequest(prompt=prompt)

            chain = router.rank(req)
            model_name = chain[0][0].name if chain else "unknown"
            provider_name = chain[0][0].provider if chain else "unknown"

            for chunk in router.stream(req):
                payload = json.dumps(chunk)
                self.window.evaluate_js(f"window._nex.appendToken({payload})")

            meta = json.dumps({"model": model_name, "provider": provider_name})
            self.window.evaluate_js(f"window._nex.onStreamEnd({meta})")
        except Exception as exc:
            msg = json.dumps(str(exc))
            if self.window:
                self.window.evaluate_js(f"window._nex.onStreamError({msg})")

    def _ensure_hw(self) -> None:
        if self._hw is None:
            from ...platform import detect, choose_profile
            self._hw = detect()
            self._profile = choose_profile(self._hw)

    # -- Konfiguration ---------------------------------------------------------

    def get_config(self) -> dict:
        from ...platform import config as cfg_mod
        cfg = cfg_mod.load()
        return {
            "role": cfg.role,
            "profile": cfg.profile,
            "daily_budget": cfg.daily_budget,
            "persona": cfg.persona,
            "house_base": cfg.house_base,
            "keys": {
                "anthropic": bool(cfg_mod.get_key("ANTHROPIC_API_KEY")),
                "openai":    bool(cfg_mod.get_key("OPENAI_API_KEY")),
                "gemini":    bool(cfg_mod.get_key("GEMINI_API_KEY")),
            },
        }

    def save_config(self, data: dict) -> dict:
        from ...platform import config as cfg_mod
        cfg = cfg_mod.load()
        if "daily_budget" in data:
            try:
                cfg.daily_budget = float(data["daily_budget"])
            except (ValueError, TypeError):
                pass
        if "persona" in data:
            cfg.persona = str(data["persona"])[:500]
        cfg_mod.save(cfg)
        for field, env_name in [
            ("anthropic_key", "ANTHROPIC_API_KEY"),
            ("openai_key",    "OPENAI_API_KEY"),
            ("gemini_key",    "GEMINI_API_KEY"),
        ]:
            val = str(data.get(field, "")).strip()
            if val:
                cfg_mod.set_secret(env_name, val)
        return {"ok": True}

    # -- Onboarding ------------------------------------------------------------

    def is_onboarding_needed(self) -> bool:
        return not (Path.home() / ".nexoryx" / "gui_onboarding_done").exists()

    def mark_onboarding_done(self) -> None:
        p = Path.home() / ".nexoryx" / "gui_onboarding_done"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.touch()


# ── Einstiegspunkt ────────────────────────────────────────────────────────────

def run() -> int:
    try:
        import webview  # type: ignore
    except ImportError:
        print("pywebview nicht installiert.")
        print("  pip install pywebview")
        if sys.platform == "linux":
            print("  Linux zusätzlich: sudo apt install python3-gi python3-gi-cairo gir1.2-webkit2-4.1")
        return 1

    daemon = _DaemonManager()
    api = NexoryxAPI(daemon)

    # PID-Lock: verhindert doppelte GUI-Instanzen
    pid_lock = Path.home() / ".nexoryx" / "gui.pid"
    pid_lock.parent.mkdir(parents=True, exist_ok=True)
    if pid_lock.exists():
        try:
            old_pid = int(pid_lock.read_text().strip())
            import os, signal
            os.kill(old_pid, 0)  # wirft OSError wenn PID tot
            print(f"Nexoryx-GUI läuft bereits (PID {old_pid}).")
            return 0
        except (ValueError, OSError):
            pass
    pid_lock.write_text(str(subprocess.os.getpid() if hasattr(subprocess, 'os') else __import__('os').getpid()))

    index_html = _STATIC / "index.html"
    if not index_html.exists():
        print(f"GUI-Dateien fehlen: {index_html}")
        pid_lock.unlink(missing_ok=True)
        return 1

    window = webview.create_window(
        title="Nexoryx",
        url=str(index_html),
        js_api=api,
        width=1200,
        height=800,
        min_size=(800, 600),
        background_color="#07090d",
    )

    def on_loaded():
        api.window = webview.windows[0] if webview.windows else window

    try:
        webview.start(on_loaded, debug=False)
    finally:
        pid_lock.unlink(missing_ok=True)

    return 0

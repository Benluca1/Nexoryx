"""nexoryxd — schlanker HTTP-JSON-Daemon (stdlib, zero-dependency).

Endpunkte:
  GET  /status        → Profil, Modelle, Rolle
  GET  /health        → {ok: true}
  POST /ask {prompt}  → {text, model, provider}

Bindet standardmäßig nur localhost. CLI/Telegram/Web können dünne Clients sein.
FastAPI-Variante ist im Plan vorgesehen; das hier ist der abhängigkeitsfreie Kern.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ..brain import classify
from ..platform import choose_profile, detect
from ..platform import config as cfg_mod
from ..router import ChatRequest, Router, available_models


def _build_handler():
    hw = detect()
    profile = choose_profile(hw)
    router = Router(hw, profile)
    cfg = cfg_mod.load()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):  # ruhiger Output
            pass

        def _send(self, code: int, obj: dict) -> None:
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/health":
                return self._send(200, {"ok": True})
            if self.path == "/status":
                models = [{"model": s.name, "provider": p.name, "local": s.is_local}
                          for s, p in available_models()]
                return self._send(200, {
                    "profile": profile.name,
                    "role": cfg.role,
                    "cpu": hw.cpu_model,
                    "ram_mb": hw.ram_mb,
                    "gpu": hw.gpu.vendor,
                    "models": models,
                })
            return self._send(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/ask":
                return self._send(404, {"error": "not found"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                data = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            except (ValueError, OSError):
                return self._send(400, {"error": "bad json"})
            prompt = (data.get("prompt") or "").strip()
            if not prompt:
                return self._send(400, {"error": "prompt fehlt"})
            brain = classify(prompt)
            if brain.trivial and brain.canned:
                return self._send(200, {"text": brain.canned, "model": "brain", "provider": "local"})
            try:
                resp = router.route(ChatRequest(prompt=prompt, task_type=brain.task_type))
            except Exception as exc:  # noqa: BLE001 - Daemon soll nicht crashen
                return self._send(500, {"error": str(exc)})
            return self._send(200, {"text": resp.text, "model": resp.model, "provider": resp.provider})

    return Handler


def serve(host: str = "127.0.0.1", port: int = 3008) -> None:
    handler = _build_handler()
    httpd = ThreadingHTTPServer((host, port), handler)
    print(f"nexoryxd läuft auf http://{host}:{port}  (Ctrl-C zum Beenden)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nnexoryxd beendet.")
        httpd.shutdown()

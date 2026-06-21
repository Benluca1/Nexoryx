"""nexoryxd — schlanker HTTP-JSON-Daemon (stdlib, zero-dependency).

Endpunkte:
  GET  /status                  → Profil, Modelle, Rolle
  GET  /health                  → {ok: true}
  POST /ask {prompt}            → {text, model, provider}
  POST /training/upload         → Trainingsdaten von Geräten entgegennehmen + zu GitHub pushen
                                  Body: {"device": "...", "jsonl": "...", "token": "..."}
                                  Token = server-secret aus ~/.nexoryx/server-secret
                                  → kein Setup auf Client-Geräten nötig

Bindet standardmäßig nur localhost; für LAN-Zugriff mit --host 0.0.0.0 starten.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ..brain import classify
from ..platform import choose_profile, detect
from ..platform import config as cfg_mod
from ..router import ChatRequest, Router, available_models

_SERVER_SECRET_FILE = Path.home() / ".nexoryx" / "server-secret"


def _load_server_secret() -> str:
    try:
        return _SERVER_SECRET_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _build_handler():
    hw = detect()
    profile = choose_profile(hw)
    router = Router(hw, profile)
    cfg = cfg_mod.load()
    server_secret = _load_server_secret()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def _send(self, code: int, obj: dict) -> None:
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_body(self) -> dict:
            length = int(self.headers.get("Content-Length", "0"))
            return json.loads(self.rfile.read(length).decode("utf-8") or "{}")

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
            try:
                data = self._read_body()
            except (ValueError, OSError):
                return self._send(400, {"error": "bad json"})

            if self.path == "/ask":
                return self._handle_ask(data)
            if self.path == "/training/upload":
                return self._handle_training(data)
            return self._send(404, {"error": "not found"})

        def _handle_ask(self, data: dict):
            prompt = (data.get("prompt") or "").strip()
            if not prompt:
                return self._send(400, {"error": "prompt fehlt"})
            brain = classify(prompt)
            if brain.trivial and brain.canned:
                return self._send(200, {"text": brain.canned, "model": "brain", "provider": "local"})
            try:
                resp = router.route(ChatRequest(prompt=prompt, task_type=brain.task_type))
            except Exception as exc:
                return self._send(500, {"error": str(exc)})
            return self._send(200, {"text": resp.text, "model": resp.model, "provider": resp.provider})

        def _handle_training(self, data: dict):
            """Trainingsdaten von einem Client-Gerät empfangen und zu GitHub pushen.

            Body: {
              "device":  "acer",          # Hostname des Absenders
              "jsonl":   "...",           # ChatML-JSONL-Inhalt
              "token":   "server-secret"  # Authentifizierung
            }
            """
            # Token-Prüfung (server-secret)
            if server_secret and data.get("token") != server_secret:
                return self._send(403, {"error": "ungültiges Token"})

            device = str(data.get("device") or "unknown")[:30]
            jsonl  = str(data.get("jsonl") or "").strip()
            if not jsonl:
                return self._send(400, {"error": "jsonl fehlt"})

            # In Repo schreiben
            try:
                from ..training.on_exit import TRAINING_DATA, REPO_ROOT, _git_push
                TRAINING_DATA.mkdir(parents=True, exist_ok=True)
                dest = TRAINING_DATA / f"{device}.jsonl"
                # Neue Zeilen anhängen (nicht überschreiben → Daten akkumulieren)
                with open(dest, "a", encoding="utf-8") as fh:
                    for line in jsonl.splitlines():
                        line = line.strip()
                        if line:
                            fh.write(line + "\n")
                n = sum(1 for _ in open(dest, encoding="utf-8"))
            except Exception as exc:
                return self._send(500, {"error": f"Schreiben fehlgeschlagen: {exc}"})

            # Git-Push (asynchron, damit der Client nicht wartet)
            import threading
            def _push():
                try:
                    _git_push(lambda m: None, n)
                except Exception:
                    pass
            threading.Thread(target=_push, daemon=True).start()

            return self._send(200, {"ok": True, "device": device, "lines": n})

    return Handler


def serve(host: str = "127.0.0.1", port: int = 3008) -> None:
    try:
        from ..platform.scanner import check_pending, start_background_scan
        check_pending()
        start_background_scan()
    except Exception:
        pass

    handler = _build_handler()
    httpd = ThreadingHTTPServer((host, port), handler)
    print(f"nexoryxd läuft auf http://{host}:{port}  (Ctrl-C zum Beenden)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nnexoryxd beendet.")
        httpd.shutdown()

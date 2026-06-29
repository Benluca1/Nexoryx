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


def _build_handler(router: Router | None = None):
    hw = detect()
    profile = choose_profile(hw)
    if router is None:
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
            if self.path == "/training/status":
                return self._handle_training_status()
            if self.path == "/admin/model/nex_admin":
                return self._handle_admin_model()
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
            if self.path == "/memory/search":
                return self._handle_memory_search(data)
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

        def _handle_admin_model(self):
            """Liefert das nex_admin-Modelfile (nur mit gültigem server-secret)."""
            auth = self.headers.get("Authorization", "")
            if not server_secret or auth != f"Bearer {server_secret}":
                return self._send(403, {"error": "unauthorized"})
            mf_path = (
                Path(__file__).resolve().parents[3]
                / "training" / "modelfiles" / "nex_admin.modelfile"
            )
            if not mf_path.exists():
                return self._send(404, {"error": "modelfile not found"})
            try:
                body = mf_path.read_bytes()
            except Exception as exc:
                return self._send(500, {"error": str(exc)})
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _handle_training_status(self):
            try:
                from ..training.dataset import stats
                st = stats()
            except Exception:
                st = {}
            return self._send(200, {
                "house_trained":  cfg.house_trained,
                "house_version":  cfg.house_version,
                "house_base":     cfg.house_base,
                "dataset_size":   st.get("total", 0),
            })

        def _handle_memory_search(self, data: dict):
            query = str(data.get("query") or "").strip()
            if not query:
                return self._send(400, {"error": "query fehlt"})
            try:
                from ..memory.store import MemoryStore
                mem = MemoryStore()
                results = mem.recall(query, limit=10)
                return self._send(200, {
                    "results": [
                        {"text": m.text, "scope": m.scope}
                        for m in results
                    ]
                })
            except Exception as exc:
                return self._send(500, {"error": str(exc)})

    return Handler


def serve(host: str = "127.0.0.1", port: int = 3008) -> None:
    # Router einmal bauen — wird von Handler und Scheduler geteilt
    hw = detect()
    profile = choose_profile(hw)
    shared_router = Router(hw, profile)

    try:
        from ..platform.scanner import check_pending, start_background_scan
        check_pending()
        start_background_scan()
    except Exception:
        pass

    # Telegram-Bot automatisch im Hintergrund starten (mit Watchdog-Auto-Restart)
    try:
        from ..interfaces.telegram.bot import start_background as _tg_start
        tg_thread = _tg_start()
        if tg_thread:
            print("Telegram-Bot: gestartet (Watchdog-Thread, auto-restart aktiv)")
        else:
            print("Telegram-Bot: kein Token — übersprungen (nexoryx admin telegram)")
    except Exception as exc:
        print(f"Telegram-Bot: Fehler beim Start — {exc}")

    # Auto-Trainer-Scheduler im Hintergrund starten (Router + Bus übergeben)
    try:
        from ..orchestrator.bus import Bus as _Bus
        from ..training.scheduler import start_background as _trainer_start
        _daemon_bus = _Bus()
        _trainer_start(router=shared_router, bus=_daemon_bus)
        print("Auto-Trainer: gestartet (prüft stündlich auf neue Trainingsdaten)")
    except Exception as exc:
        print(f"Auto-Trainer: Fehler beim Start — {exc}")

    handler = _build_handler(router=shared_router)
    httpd = ThreadingHTTPServer((host, port), handler)
    print(f"nexoryxd läuft auf http://{host}:{port}  (Ctrl-C zum Beenden)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nnexoryxd beendet.")
        httpd.shutdown()

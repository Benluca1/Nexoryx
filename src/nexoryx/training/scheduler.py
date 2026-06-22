"""Automatischer Trainings-Scheduler — läuft als Hintergrund-Thread im Daemon.

Prüft stündlich ob genug neue Daten vorliegen und löst das Training des
Hausmodells automatisch aus. Benachrichtigt per Telegram wenn Training
startet oder abgeschlossen ist.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

_CHECK_INTERVAL = 3600      # jede Stunde prüfen
_MIN_NEW_EXAMPLES = 50      # Mindestanzahl neuer Beispiele seit letztem Training
_LAST_COUNT_FILE = Path.home() / ".nexoryx" / "last_trained_count"


def _load_last_count() -> int:
    try:
        return int(_LAST_COUNT_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0


def _save_last_count(n: int) -> None:
    _LAST_COUNT_FILE.parent.mkdir(parents=True, exist_ok=True)
    _LAST_COUNT_FILE.write_text(str(n), encoding="utf-8")


def _notify_telegram(message: str) -> None:
    try:
        from ..platform import config as cfg_mod
        from ..interfaces.telegram.bot import _api, _send
        token = cfg_mod.get_key("TELEGRAM_BOT_TOKEN")
        if not token:
            return
        cfg = cfg_mod.load()
        admin_id = getattr(cfg, "telegram_admin_id", None)
        if admin_id:
            _send(token, admin_id, message)
    except Exception:
        pass


def _run_scheduler(stop_event: threading.Event) -> None:
    print("[AutoTrainer] Scheduler gestartet — prüfe stündlich auf neue Trainingsdaten.")
    while not stop_event.is_set():
        try:
            _check_and_train()
        except Exception as exc:
            print(f"[AutoTrainer] Fehler: {exc}")
        stop_event.wait(_CHECK_INTERVAL)


def _check_and_train() -> None:
    from . import dataset
    from .train import train, MIN_EXAMPLES

    stats = dataset.stats()
    total = stats["total"]
    last_count = _load_last_count()
    new_since_last = total - last_count

    print(f"[AutoTrainer] Datensatz: {total} Beispiele gesamt, {new_since_last} neu seit letztem Training.")

    if total < MIN_EXAMPLES:
        print(f"[AutoTrainer] Noch {MIN_EXAMPLES - total} Beispiele bis Mindestanzahl — übersprungen.")
        return

    if new_since_last < _MIN_NEW_EXAMPLES:
        print(f"[AutoTrainer] Nur {new_since_last} neue Beispiele (min. {_MIN_NEW_EXAMPLES}) — warte auf mehr Daten.")
        return

    print(f"[AutoTrainer] Starte automatisches Training ({total} Beispiele, {new_since_last} neu) …")
    _notify_telegram(
        f"🏋️ *Auto-Training gestartet*\n"
        f"Datensatz: {total} Beispiele ({new_since_last} neu)\n"
        f"Läuft im Hintergrund …"
    )

    try:
        out_dir = Path.home() / ".nexoryx" / "auto_training"
        result = train(repo_root=out_dir)
        action = result.get("action", "?")

        if action == "trained":
            version = result.get("house_version", "?")
            print(f"[AutoTrainer] Training abgeschlossen — Version {version}")
            _notify_telegram(
                f"✅ *Auto-Training abgeschlossen*\n"
                f"Hausmodell Version {version} trainiert."
            )
            _save_last_count(total)

        elif action == "script_generated":
            deps = ", ".join(result.get("deps_missing", []))
            print(f"[AutoTrainer] Training-Skript erzeugt (fehlende Deps: {deps})")
            _notify_telegram(
                f"📝 *Auto-Training: Skript erzeugt*\n"
                f"Fehlende Pakete: {deps}\n"
                f"Führe aus: {result.get('instructions', '')}"
            )
            _save_last_count(total)

        elif action == "skipped":
            print(f"[AutoTrainer] Übersprungen: {result.get('reason', '?')}")

        elif action == "failed":
            err = result.get("error", "?")
            print(f"[AutoTrainer] Training fehlgeschlagen: {err}")
            _notify_telegram(f"❌ *Auto-Training fehlgeschlagen*\n{err}")

    except Exception as exc:
        print(f"[AutoTrainer] Ausnahme während Training: {exc}")
        _notify_telegram(f"❌ *Auto-Training Ausnahme:* {exc}")


def start_background() -> threading.Thread:
    """Startet den automatischen Trainings-Scheduler als Daemon-Thread."""
    stop_event = threading.Event()
    t = threading.Thread(
        target=_run_scheduler,
        args=(stop_event,),
        daemon=True,
        name="nexoryx-auto-trainer",
    )
    t.stop_event = stop_event  # type: ignore[attr-defined]
    t.start()
    return t

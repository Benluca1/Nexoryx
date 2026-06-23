"""Automatischer Trainings-Scheduler — läuft als Hintergrund-Thread im Daemon.

Prüft stündlich ob genug neue Daten vorliegen und startet dann den
TrainingAgent im Hintergrund. Benachrichtigt per Telegram wenn Training
startet oder abgeschlossen ist.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..router import Router
    from ..orchestrator.bus import Bus

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
        from ..interfaces.telegram.bot import _send
        token = cfg_mod.get_key("TELEGRAM_BOT_TOKEN")
        if not token:
            return
        cfg = cfg_mod.load()
        admin_id = getattr(cfg, "telegram_admin_id", None)
        if admin_id:
            _send(token, admin_id, message)
    except Exception:
        pass


def _run_scheduler(stop_event: threading.Event,
                   router: "Router | None",
                   bus: "Bus | None") -> None:
    print("[AutoTrainer] Scheduler gestartet — prüfe stündlich auf neue Trainingsdaten.")
    while not stop_event.is_set():
        try:
            _check_and_train(router, bus)
        except Exception as exc:
            print(f"[AutoTrainer] Fehler: {exc}")
        stop_event.wait(_CHECK_INTERVAL)


def _check_and_train(router: "Router | None", bus: "Bus | None") -> None:
    from . import dataset
    from .train import MIN_EXAMPLES
    from ..agents.training import TrainingAgent

    stats = dataset.stats()
    total = stats["total"]
    last_count = _load_last_count()
    new_since_last = total - last_count

    print(
        f"[AutoTrainer] Datensatz: {total} Beispiele gesamt, "
        f"{new_since_last} neu seit letztem Training."
    )

    if total < MIN_EXAMPLES:
        print(f"[AutoTrainer] Noch {MIN_EXAMPLES - total} Beispiele bis Mindestanzahl — übersprungen.")
        return

    if new_since_last < _MIN_NEW_EXAMPLES:
        print(
            f"[AutoTrainer] Nur {new_since_last} neue Beispiele "
            f"(min. {_MIN_NEW_EXAMPLES}) — warte auf mehr Daten."
        )
        return

    print(
        f"[AutoTrainer] Starte TrainingAgent "
        f"({total} Beispiele, {new_since_last} neu) …"
    )
    _notify_telegram(
        f"🏋️ *Auto-Training gestartet*\n"
        f"Datensatz: {total} Beispiele ({new_since_last} neu)\n"
        f"Läuft im Hintergrund …"
    )

    agent = TrainingAgent(router=router, bus=bus)
    out_dir = Path.home() / ".nexoryx" / "auto_training"

    def _on_done(n: int, result: dict) -> None:
        # Zähler immer vorrücken (auch bei Ablehnung), sonst Endlos-Retry.
        _save_last_count(n)
        action = result.get("action", "")
        if action == "rejected":
            ev = result.get("eval", {})
            _notify_telegram(
                f"↩️ *Auto-Training: neue Version verworfen*\n"
                f"Eval-Gate: Kandidat {ev.get('candidate_score')} "
                f"< Baseline {ev.get('incumbent_score')}.\n"
                f"Bisheriges Modell `{result.get('kept', '?')}` bleibt aktiv."
            )
        elif action == "trained":
            ev = result.get("eval", {})
            score = ev.get("candidate_score")
            _notify_telegram(
                f"✅ *Auto-Training abgeschlossen*\n"
                f"Hausmodell v{result.get('house_version', '?')} aktiviert "
                f"({n} Beispiele"
                + (f", Eval-Score {score}" if score is not None else "") + ")."
            )
        elif action == "script_generated":
            deps = ", ".join(result.get("deps_missing", []))
            _notify_telegram(
                f"📝 *Auto-Training: Skript erzeugt*\n"
                f"Fehlende Pakete: {deps or '–'}\n"
                f"Ausführen: `{result.get('instructions', '')}`"
            )

    thread = agent.run_background(repo_root=out_dir, on_success=_on_done)
    if thread is None:
        print("[AutoTrainer] Training läuft bereits — dieser Zyklus übersprungen.")


def start_background(
    router: "Router | None" = None,
    bus: "Bus | None" = None,
) -> threading.Thread:
    """Startet den automatischen Trainings-Scheduler als Daemon-Thread."""
    stop_event = threading.Event()
    t = threading.Thread(
        target=_run_scheduler,
        args=(stop_event, router, bus),
        daemon=True,
        name="nexoryx-auto-trainer",
    )
    t.stop_event = stop_event  # type: ignore[attr-defined]
    t.start()
    return t

"""TrainingAgent — schult das Hausmodell automatisch im Hintergrund.

Wird vom Scheduler gestartet wenn genug neue Daten vorliegen. Läuft als
Daemon-Thread (Mutex verhindert parallele Läufe). Nutzt das lokale Modell
optional zur Datensatz-Anreicherung, damit das Modell Schritt für Schritt
besser wird.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Callable

from ..orchestrator.bus import Bus
from ..router import ChatRequest, Router
from ..training import dataset
from ..training.train import MIN_EXAMPLES, train

_LOCK = threading.Lock()
_LOCAL_PROVIDERS = {"ollama", "llamacpp", "local_llamacpp", "local-fallback"}


class TrainingAgent:
    """Hintergrund-Agent für das automatische Training des Hausmodells."""

    def __init__(self, router: Router | None = None, bus: Bus | None = None) -> None:
        self.router = router
        self.bus = bus or Bus()

    # ── öffentliche API ────────────────────────────────────────────────────

    def run(self, repo_root: Path | None = None,
            on_success: Callable[[int, dict], None] | None = None) -> dict:
        """Führt den kompletten Trainingszyklus synchron durch."""
        self.bus.publish("training.started")
        stats = dataset.stats()

        enriched = 0
        if self.router is not None and stats["total"] >= MIN_EXAMPLES * 2:
            try:
                enriched = self._enrich_dataset()
            except Exception as exc:
                print(f"[TrainingAgent] Anreicherung fehlgeschlagen: {exc}")

        result = train(repo_root=repo_root)
        result["enriched_examples"] = enriched
        action = result.get("action", "")

        if action == "trained":
            v = result.get("house_version", "?")
            print(
                f"[TrainingAgent] ✓ Hausmodell v{v} trainiert "
                f"({stats['total']} Beispiele, {enriched} synthetisch hinzugefügt)"
            )
            self.bus.publish("training.done", version=v, total=stats["total"])
            if on_success:
                on_success(stats["total"], result)

        elif action == "script_generated":
            print(f"[TrainingAgent] Trainings-Skript erzeugt: {result.get('script', '?')}")
            self.bus.publish("training.script_ready", **{
                k: v for k, v in result.items() if k != "action"
            })
            if on_success:
                on_success(stats["total"], result)

        elif action == "rejected":
            ev = result.get("eval", {})
            print(
                f"[TrainingAgent] ✗ Eval-Gate: neue Version verworfen — "
                f"Kandidat {ev.get('candidate_score')} < Baseline {ev.get('incumbent_score')}. "
                f"Behalte {result.get('kept', '?')}."
            )
            self.bus.publish("training.rejected", **ev)
            # Zähler trotzdem vorrücken: gleiche Daten → gleiches Ergebnis,
            # sonst stündliche Wiederholung derselben Ablehnung.
            if on_success:
                on_success(stats["total"], result)

        elif action == "failed":
            print(f"[TrainingAgent] ✗ Fehler: {result.get('error', '?')}")
            self.bus.publish("training.failed", error=result.get("error", "?"))

        return result

    def run_background(
        self,
        repo_root: Path | None = None,
        on_success: Callable[[int, dict], None] | None = None,
    ) -> threading.Thread | None:
        """Startet den Trainingszyklus als Daemon-Thread.

        Gibt None zurück wenn bereits ein Training läuft.
        """
        if not _LOCK.acquire(blocking=False):
            print("[TrainingAgent] Training läuft bereits — neuer Lauf übersprungen.")
            return None

        def _target() -> None:
            try:
                self.run(repo_root=repo_root, on_success=on_success)
            except Exception as exc:
                print(f"[TrainingAgent] Unbehandelte Ausnahme: {exc}")
                self.bus.publish("training.failed", error=str(exc))
            finally:
                _LOCK.release()

        t = threading.Thread(target=_target, daemon=True, name="nexoryx-training-agent")
        t.start()
        return t

    # ── Datensatz-Anreicherung via lokalem Modell ──────────────────────────

    def _enrich_dataset(self) -> int:
        """Generiert bis zu 3 synthetische Beispiele via lokalem Modell.

        Verwendet nur Teacher-Beispiele als Vorlage um Stilkonsistenz zu
        wahren. Wird nur aufgerufen wenn mindestens 2×MIN_EXAMPLES echte
        Daten vorliegen, damit schlechte Synthese nicht dominiert.
        """
        templates: list[dict] = []
        for ex in dataset.iter_examples():
            if ex.get("teacher"):
                templates.append(ex)
            if len(templates) >= 2:
                break
        if not templates:
            return 0

        context = "\n".join(
            f"Nutzer: {_first_msg(ex, 'user')[:200]}\n"
            f"Nexoryx: {_first_msg(ex, 'assistant')[:300]}"
            for ex in templates
        )
        prompt = (
            f"Hier sind echte Gespräche mit einem KI-Assistenten:\n{context}\n\n"
            "Erstelle 3 neue kurze Frage-Antwort-Paare im selben Stil auf Deutsch.\n"
            "Halte dich STRIKT an dieses Format:\n"
            "FRAGE: <frage> ANTWORT: <antwort>"
        )
        req = ChatRequest(
            prompt=prompt,
            system=(
                "Du erzeugst Trainingsdaten für einen KI-Assistenten. "
                "Kurze, natürliche, hilfreiche Deutsch-Dialoge."
            ),
            task_type="summarize",
            max_tokens=500,
        )
        # Distillation braucht ein starkes Lehrer-Signal: NICHT prefer_fast,
        # sonst erzeugt das schwache lokale Modell Daten für sich selbst
        # (Model-Collapse). Lokale Antworten werden verworfen.
        resp = self.router.route(req, prefer_fast=False)
        if resp.provider in _LOCAL_PROVIDERS:
            print(
                "[TrainingAgent] Anreicherung übersprungen — "
                "kein Cloud-Teacher verfügbar (schwache Selbst-Generierung vermieden)."
            )
            return 0
        return _record_synthetic(resp.text)


# ── Hilfsfunktionen ──────────────────────────────────────────────────────────

def _first_msg(ex: dict, role: str) -> str:
    for m in ex.get("messages", []):
        if m.get("role") == role:
            return m.get("content", "")
    return ""


def _record_synthetic(text: str) -> int:
    """Parst FRAGE/ANTWORT-Paare und speichert sie im Datensatz."""
    pairs = re.findall(
        r"FRAGE:\s*(.+?)\s*ANTWORT:\s*(.+?)(?=FRAGE:|$)", text, re.DOTALL
    )
    count = 0
    for question, answer in pairs:
        question, answer = question.strip(), answer.strip()
        if len(question) < 5 or len(answer) < 10:
            continue
        dataset.record_interaction(
            prompt=question,
            system="Du bist Nexoryx, ein hilfreicher KI-Assistent.",
            response=answer,
            provider="synthetic",
            model="teacher",
            task_type="chat",
            is_local=False,  # vom Cloud-Teacher destilliert
        )
        count += 1
    return count

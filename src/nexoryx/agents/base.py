"""Agent-Basis — jeder Agent ist eine Rolle (System-Prompt) über dem Router."""

from __future__ import annotations

from dataclasses import dataclass

from ..router import ChatRequest, Router


@dataclass
class Agent:
    name: str
    system: str
    task_type: str = "chat"

    def act(self, router: Router, prompt: str, prefer_fast: bool = False,
            max_tokens: int = 1024) -> str:
        req = ChatRequest(
            prompt=prompt, system=self.system,
            task_type=self.task_type, max_tokens=max_tokens,
        )
        return router.route(req, prefer_fast=prefer_fast).text


# Registry der Standard-Agenten (Plan §6.3).
AGENTS: dict[str, Agent] = {
    "planner": Agent(
        "planner",
        "Du bist der Planner-Agent von Nexoryx. Zerlege die Aufgabe in 2–5 "
        "knappe, nummerierte Schritte. Keine Ausführung, nur der Plan.",
        task_type="reasoning",
    ),
    "coder": Agent(
        "coder",
        "Du bist der Coder-Agent von Nexoryx. Schreibe korrekten, knappen Code "
        "mit kurzer Erklärung. Nutze Markdown-Codeblöcke.",
        task_type="coding",
    ),
    "research": Agent(
        "research",
        "Du bist der Research-Agent. Fasse zusammen, nenne Annahmen und "
        "kennzeichne Unsicherheit klar.",
        task_type="research",
    ),
    "debug": Agent(
        "debug",
        "Du bist der Debug-Agent. Analysiere Fehler, nenne wahrscheinliche "
        "Ursache und konkreten Fix.",
        task_type="coding",
    ),
    "memory": Agent(
        "memory",
        "Du bist der Memory-Agent. Extrahiere aus dem Dialog dauerhafte Fakten "
        "und Präferenzen als kurze Stichpunkte (max 5). Nur Fakten, keine Floskeln.",
        task_type="summarize",
    ),
}

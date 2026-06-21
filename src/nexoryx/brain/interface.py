"""Bootstrap-Brain (regelbasiert).

Übernimmt die Rolle des Nexoryx-Tiny-Models, bis dieses trainiert ist
(Plan §3.3 Bootstrap-Pfad): klassifiziert den Task-Typ aus dem Prompt, damit
der Router passend gewichten kann. Gleiches `classify`-Interface bleibt, wenn
später das echte Tiny-Model (GGUF) eingehängt wird.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Schlüsselwörter pro Task-Typ (DE + EN). Reihenfolge = Priorität.
_KEYWORDS = {
    "coding": (
        "code", "function", "bug", "fehler", "kompil", "compile", "python",
        "javascript", "refactor", "klasse", "class", "api", "regex", "stack trace",
    ),
    "reasoning": (
        "warum", "why", "erklär", "explain", "beweis", "prove", "rechne",
        "calculate", "löse", "solve", "schritt für schritt", "step by step",
    ),
    "research": (
        "such", "search", "recherch", "research", "quelle", "source", "news",
        "aktuell", "latest", "vergleich", "compare",
    ),
    "summarize": (
        "zusammenfass", "summar", "tl;dr", "tldr", "kürze", "shorten", "extrahier",
        "extract",
    ),
}

# Sehr kurze Trivial-Anfragen → können vom Brain selbst beantwortet werden.
_TRIVIAL = re.compile(r"^\s*(hi|hallo|hello|hey|danke|thanks|ok|test)\s*[!.?]*\s*$", re.I)


@dataclass
class BrainResult:
    task_type: str  # coding|reasoning|research|summarize|chat
    trivial: bool
    canned: str = ""  # direkte Antwort, falls trivial


def classify(prompt: str) -> BrainResult:
    if _TRIVIAL.match(prompt):
        return BrainResult(task_type="chat", trivial=True, canned="Hallo! Wie kann ich helfen?")
    low = prompt.lower()
    for task, words in _KEYWORDS.items():
        if any(w in low for w in words):
            return BrainResult(task_type=task, trivial=False)
    return BrainResult(task_type="chat", trivial=False)

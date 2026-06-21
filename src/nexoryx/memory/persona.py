"""Nutzer-Persona — persistiert Wissen über den User in .md-Dateien.

Nach jeder Sitzung wird analysiert ob neue lernbare Fakten aufgetaucht sind.
Beim Start werden alle .md-Dateien geladen und in den System-Prompt injiziert,
damit Nexoryx sofort weiß wie er mit diesem Nutzer reden soll.

Dateien unter ~/.nexoryx/memory/:
  user.md       — wer ist der User (Name, Beruf, Interessen, ...)
  behavior.md   — wie soll Nexoryx sich verhalten (Sprache, Ton, ...)
  corrections.md — was hat der User korrigiert / was soll anders laufen
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from ..platform.config import CONFIG_DIR

MEMORY_DIR = CONFIG_DIR / "memory"

# (Datei, Regex-Muster) — matched → Fakt in die Datei schreiben
_LEARN_PATTERNS: list[tuple[str, list[str]]] = [
    ("user.md", [
        r"ich hei[ßs]e\s+(.+)",
        r"mein name ist\s+(.+)",
        r"ich bin\s+(\d+)\s*jahre",
        r"ich arbeite als\s+(.+)",
        r"ich bin (?:von beruf|beruflich)\s+(.+)",
        r"ich komme aus\s+(.+)",
        r"ich wohne in\s+(.+)",
        r"ich studiere\s+(.+)",
        r"my name is\s+(.+)",
        r"i (?:am|work as)\s+(.+)",
        r"i live in\s+(.+)",
    ]),
    ("behavior.md", [
        r"merk dir (?:immer\s+)?(?:dass\s+)?(.+)",
        r"denk(?:e)? immer daran[,:]?\s*(.+)",
        r"du sollst (?:immer\s+)?(.+)",
        r"du musst (?:immer\s+)?(.+)",
        r"antworte (?:mir\s+)?immer\s+(.+)",
        r"sprich mich (?:bitte\s+)?(?:immer\s+)?(?:mit\s+)?(.+?)\s+an",
        r"sei (?:immer\s+)?(.+?)(?:\.|$)",
        r"please (?:always\s+)?(?:remember\s+)?(.+)",
        r"always\s+(.+)",
        r"remember that\s+(.+)",
    ]),
    ("corrections.md", [
        r"das (?:war\s+)?(?:ist\s+)?(?:nicht|falsch|wrong)[,:]?\s*(.+)",
        r"nicht so[,:]?\s+(.+)",
        r"(?:mach|tue)\s+(?:das\s+)?(?:nicht|nie)\s+(?:mehr\s+)?(.+)",
        r"h[oö]r auf\s+(?:damit\s+)?(.+)",
        r"don't\s+(.+)",
        r"stop\s+(.+)",
        r"never\s+(.+)",
    ]),
]


def load() -> str:
    """Lädt alle .md-Dateien und gibt sie als System-Prompt-Abschnitt zurück."""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    parts: list[str] = []
    for fname in ("user.md", "behavior.md", "corrections.md"):
        p = MEMORY_DIR / fname
        if p.exists():
            content = p.read_text(encoding="utf-8").strip()
            if content:
                parts.append(content)
    return "\n\n".join(parts)


def learn_from_turn(user_msg: str, bot_msg: str) -> list[str]:
    """Analysiert einen Gesprächs-Turn auf lernbare Fakten.

    Gibt Liste der Dateien zurück in die geschrieben wurde.
    """
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    combined = f"{user_msg}\n{bot_msg}".lower()

    for fname, patterns in _LEARN_PATTERNS:
        new_facts: list[str] = []
        for pat in patterns:
            for m in re.finditer(pat, combined, re.IGNORECASE):
                fact = m.group(1).strip().rstrip(".,!?")
                if fact and len(fact) > 2:
                    new_facts.append(fact)

        if new_facts:
            _append_facts(fname, new_facts)
            written.append(fname)

    return written


def learn_from_history(history: list[str], model_fn=None) -> None:
    """Extrahiert Wissen aus dem gesamten Sitzungs-Verlauf.

    Falls model_fn übergeben wird (Callable[str] → str), wird das Modell
    gefragt um tiefere Fakten zu extrahieren. Sonst nur Regex.
    """
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    full_text = "\n".join(history)

    # Regex-basiert
    for fname, patterns in _LEARN_PATTERNS:
        facts: list[str] = []
        for pat in patterns:
            for m in re.finditer(pat, full_text, re.IGNORECASE):
                fact = m.group(1).strip().rstrip(".,!?")
                if fact and len(fact) > 2:
                    facts.append(fact)
        if facts:
            _append_facts(fname, facts)

    # Modell-basierte Extraktion (optional, nur wenn Modell verfügbar)
    if model_fn and len(history) >= 4:
        _model_extract(full_text, model_fn)


def _model_extract(conversation: str, model_fn) -> None:
    """Fragt das Modell nach lernbaren Fakten aus dem Gespräch."""
    try:
        prompt = (
            "Analysiere dieses Gespräch und extrahiere maximal 5 kurze, konkrete Fakten "
            "über den Nutzer oder wie der Assistent sich verhalten soll. "
            "Format: eine Zeile pro Fakt, beginne jede Zeile mit USER: oder VERHALTEN: oder KORREKTUR:\n\n"
            f"{conversation[-3000:]}\n\n"
            "Fakten (oder NICHTS wenn keine erkennbar):"
        )
        result = model_fn(prompt)
        if not result or "NICHTS" in result.upper():
            return

        user_facts, behavior_facts, correction_facts = [], [], []
        for line in result.splitlines():
            line = line.strip()
            if line.startswith("USER:"):
                user_facts.append(line[5:].strip())
            elif line.startswith("VERHALTEN:"):
                behavior_facts.append(line[10:].strip())
            elif line.startswith("KORREKTUR:"):
                correction_facts.append(line[10:].strip())

        if user_facts:
            _append_facts("user.md", user_facts)
        if behavior_facts:
            _append_facts("behavior.md", behavior_facts)
        if correction_facts:
            _append_facts("corrections.md", correction_facts)
    except Exception:
        pass


def _append_facts(fname: str, facts: list[str]) -> None:
    """Hängt neue Fakten an eine .md-Datei an (doppelte überspringen)."""
    p = MEMORY_DIR / fname
    existing = p.read_text(encoding="utf-8") if p.exists() else ""

    new_lines: list[str] = []
    for fact in facts:
        # Duplikat-Check (case-insensitive, erste 40 Zeichen)
        if fact[:40].lower() not in existing.lower():
            new_lines.append(f"- {fact}")

    if not new_lines:
        return

    ts = time.strftime("%Y-%m-%d")
    block = f"\n<!-- {ts} -->\n" + "\n".join(new_lines) + "\n"

    with open(p, "a", encoding="utf-8") as fh:
        if not existing:
            header = {
                "user.md": "# Nutzer-Profil\n",
                "behavior.md": "# Verhaltens-Regeln\n",
                "corrections.md": "# Korrekturen\n",
            }.get(fname, "")
            fh.write(header)
        fh.write(block)


def get_context() -> str:
    """Kurzer Kontext-Block für System-Prompts (max. 1000 Zeichen)."""
    text = load()
    if not text:
        return ""
    return f"[Gespeichertes Wissen über diesen Nutzer]\n{text[:1000]}\n"

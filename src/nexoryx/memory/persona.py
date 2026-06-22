"""Nutzer-Persona — persistiert Wissen über den User in .md-Dateien.

Nach jeder Sitzung wird analysiert ob neue lernbare Fakten aufgetaucht sind.
Beim Start werden alle .md-Dateien geladen und in den System-Prompt injiziert,
damit Nexoryx sofort weiß wie er mit diesem Nutzer reden soll.

Dateien unter ~/.nexoryx/memory/:
  user.md        — wer ist der User (Name, Beruf, Interessen, ...)
  behavior.md    — wie soll Nexoryx sich verhalten (Sprache, Ton, ...)
  corrections.md — was hat der User korrigiert / was soll anders laufen
  interests.md   — welche Themen/Technologien interessieren den User
  preferences.md — implizite Stil- & Formatierungs-Vorlieben
  soul.md        — Werte, Träume, Motivation, Lebensphilosophie des Users
"""
from __future__ import annotations

import json
import re
import time
from collections import Counter
from pathlib import Path

from ..platform.config import CONFIG_DIR

MEMORY_DIR = CONFIG_DIR / "memory"

# Dateinamen und ihre Markdown-Header
_FILE_HEADERS = {
    "user.md":        "# Nutzer-Profil\n",
    "behavior.md":    "# Verhaltens-Regeln\n",
    "corrections.md": "# Korrekturen\n",
    "interests.md":   "# Interessen & Themen\n",
    "preferences.md": "# Stil-Vorlieben\n",
    "soul.md":        "# Seele — Werte · Träume · Philosophie\n",
}

# (Datei, Regex-Muster) — matched → Fakt eintragen
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
        r"ich mag\s+(.+?)(?:\.|$)",
        r"ich liebe\s+(.+?)(?:\.|$)",
        r"ich benutze\s+(.+?)(?:\s+(?:täglich|immer|oft))?(?:\.|$)",
        r"my name is\s+(.+)",
        r"i (?:am|work as)\s+(.+)",
        r"i live in\s+(.+)",
        r"i use\s+(.+?)(?:\.|$)",
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
        r"ich bevorzuge\s+(.+?)(?:\.|$)",
        r"ich möchte (?:dass|immer)\s+(.+?)(?:\.|$)",
    ]),
    ("corrections.md", [
        r"das (?:war\s+)?(?:ist\s+)?(?:nicht|falsch|wrong)[,:]?\s*(.+)",
        r"nicht so[,:]?\s+(.+)",
        r"(?:mach|tue)\s+(?:das\s+)?(?:nicht|nie)\s+(?:mehr\s+)?(.+)",
        r"h[oö]r auf\s+(?:damit\s+)?(.+)",
        r"don't\s+(.+)",
        r"stop\s+(.+)",
        r"never\s+(.+)",
        r"bitte nicht\s+(.+?)(?:\.|$)",
        r"das nervt[,:]?\s*(.+)",
    ]),
    ("preferences.md", [
        r"kurze(?:re)? antworten(?:\s+bitte)?",
        r"lange(?:re)? antworten(?:\s+bitte)?",
        r"auf (?:deutsch|englisch|französisch)\s+antworten",
        r"ohne emojis?",
        r"mit emojis?",
        r"(?:kein(?:e)?|ohne)\s+(?:markdown|formatierung)",
        r"mit (?:markdown|formatierung|code-?blöcke)",
        r"erkläre\s+(?:mir\s+)?(?:immer\s+)?(?:alles\s+)?(?:einfach|simpel|verständlich)",
        r"geh davon aus(?:,)? dass ich\s+(.+?)(?:\.|$)",
        r"ich (?:bin\s+)?(?:ein\s+)?(?:erfahrener?|fortgeschrittener?|anfänger|beginner)\s+(.+)",
    ]),
    ("soul.md", [
        r"mein(?:e)?\s+(?:größter?\s+)?traum\s+(?:ist|war|wäre)\s+(.+?)(?:\.|$)",
        r"ich träume (?:davon[,]?\s+)?(.+?)(?:\.|$)",
        r"mein(?:e)?\s+(?:lebens)?ziel(?:e)?\s+(?:ist|sind|wäre)\s+(.+?)(?:\.|$)",
        r"mir ist\s+(?:es\s+)?(?:am\s+)?wichtig(?:sten)?,?\s+(?:dass\s+)?(.+?)(?:\.|$)",
        r"ich glaube\s+(?:fest\s+)?(?:daran[,]?\s+)?(?:dass\s+)?(.+?)(?:\.|$)",
        r"ich stehe für\s+(.+?)(?:\.|$)",
        r"was mich antreibt[,:]?\s+(?:ist\s+)?(.+?)(?:\.|$)",
        r"ich lebe für\s+(.+?)(?:\.|$)",
        r"meine\s+(?:größte\s+)?leidenschaft\s+(?:ist|sind)\s+(.+?)(?:\.|$)",
        r"was mich begeistert[,:]?\s+(?:ist\s+)?(.+?)(?:\.|$)",
        r"ich (?:hasse|verabscheue)\s+(.+?)(?:\.|$)",
        r"meine werte?\s+(?:sind|ist)\s+(.+?)(?:\.|$)",
        r"ich möchte\s+(?:eines\s+tages\s+)?(.+?)(?:\.|$)",
        r"my (?:biggest\s+)?dream\s+(?:is|was)\s+(.+?)(?:\.|$)",
        r"i (?:believe|stand for)\s+(.+?)(?:\.|$)",
        r"what drives me\s+(?:is\s+)?(.+?)(?:\.|$)",
        r"i (?:live|fight)\s+for\s+(.+?)(?:\.|$)",
    ]),
]

# Themen-Schlüsselwörter → interests.md
_INTEREST_KEYWORDS: dict[str, list[str]] = {
    "Python":       ["python", "pip", "django", "flask", "fastapi", "pydantic"],
    "JavaScript":   ["javascript", "js", "typescript", "node", "react", "vue", "svelte"],
    "Linux":        ["linux", "ubuntu", "debian", "bash", "shell", "systemd", "apt"],
    "KI/ML":        ["llm", "neural", "modell", "training", "pytorch", "tensorflow", "ollama", "llama"],
    "Web":          ["html", "css", "api", "http", "rest", "graphql", "nginx", "reverse proxy"],
    "Datenbanken":  ["sql", "postgres", "mysql", "sqlite", "mongodb", "redis", "datenbank"],
    "Docker":       ["docker", "container", "compose", "kubernetes", "k8s"],
    "Git/GitHub":   ["git", "github", "commit", "branch", "pull request", "merge"],
    "Sicherheit":   ["security", "sicherheit", "passwort", "verschlüsselung", "vpn", "firewall"],
    "Automatisierung": ["automatisier", "script", "cron", "workflow", "pipeline", "ci/cd"],
    "Hardware":     ["raspberry", "arduino", "gpu", "cpu", "ram", "hardware"],
    "Telegram":     ["telegram", "bot", "webhook", "polling"],
}

# Zähler-Datei für Interessen-Frequenz
_INTEREST_COUNT_FILE = MEMORY_DIR / "interest_counts.json"


def load() -> str:
    """Lädt alle .md-Dateien und gibt sie als System-Prompt-Abschnitt zurück."""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    parts: list[str] = []
    for fname in _FILE_HEADERS:
        p = MEMORY_DIR / fname
        if p.exists():
            content = p.read_text(encoding="utf-8").strip()
            if content:
                parts.append(content)
    return "\n\n".join(parts)


def get_context() -> str:
    """Kurzer Kontext-Block für System-Prompts (max. 1200 Zeichen)."""
    text = load()
    if not text:
        return ""
    return f"[Gespeichertes Wissen über diesen Nutzer]\n{text[:1200]}\n"


def learn_from_turn(user_msg: str, bot_msg: str) -> list[str]:
    """Analysiert einen Gesprächs-Turn auf lernbare Fakten."""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    combined = f"{user_msg}\n{bot_msg}"

    for fname, patterns in _LEARN_PATTERNS:
        new_facts: list[str] = []
        for pat in patterns:
            for m in re.finditer(pat, combined, re.IGNORECASE):
                try:
                    fact = m.group(1).strip().rstrip(".,!?")
                except IndexError:
                    fact = m.group(0).strip()
                if fact and len(fact) > 2:
                    new_facts.append(fact)
        if new_facts:
            _append_facts(fname, new_facts)
            written.append(fname)

    # Interessen aus Benutzer-Nachricht tracken
    _track_interests(user_msg)

    return written


def learn_from_history(history: list[str], model_fn=None) -> None:
    """Extrahiert Wissen aus dem gesamten Sitzungs-Verlauf."""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    full_text = "\n".join(history)

    for fname, patterns in _LEARN_PATTERNS:
        facts: list[str] = []
        for pat in patterns:
            for m in re.finditer(pat, full_text, re.IGNORECASE):
                try:
                    fact = m.group(1).strip().rstrip(".,!?")
                except IndexError:
                    fact = m.group(0).strip()
                if fact and len(fact) > 2:
                    facts.append(fact)
        if facts:
            _append_facts(fname, facts)

    # Interessen aus gesamter Sitzung
    _track_interests(full_text)

    # Top-Interessen in interests.md schreiben
    _flush_interests()

    # Modell-basierte Extraktion (optional)
    if model_fn and len(history) >= 4:
        _model_extract(full_text, model_fn)


def _track_interests(text: str) -> None:
    """Zählt Keyword-Treffer und aktualisiert den persistierten Counter."""
    text_lower = text.lower()
    try:
        counts = json.loads(_INTEREST_COUNT_FILE.read_text(encoding="utf-8")) if _INTEREST_COUNT_FILE.exists() else {}
    except (ValueError, OSError):
        counts = {}

    for topic, keywords in _INTEREST_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw in text_lower)
        if hits:
            counts[topic] = counts.get(topic, 0) + hits

    _INTEREST_COUNT_FILE.parent.mkdir(parents=True, exist_ok=True)
    _INTEREST_COUNT_FILE.write_text(json.dumps(counts, ensure_ascii=False, indent=2), encoding="utf-8")


def _flush_interests() -> None:
    """Schreibt Top-Interessen (≥2 Erwähnungen) in interests.md."""
    if not _INTEREST_COUNT_FILE.exists():
        return
    try:
        counts = json.loads(_INTEREST_COUNT_FILE.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return

    top = sorted([(t, c) for t, c in counts.items() if c >= 2], key=lambda x: -x[1])
    if not top:
        return

    p = MEMORY_DIR / "interests.md"
    existing = p.read_text(encoding="utf-8") if p.exists() else ""
    lines: list[str] = []
    for topic, count in top[:15]:
        entry = f"- {topic} (×{count} erwähnt)"
        if entry[:20].lower() not in existing.lower():
            lines.append(entry)

    if lines:
        _append_facts("interests.md", lines)


def all_files() -> dict[str, str]:
    """Gibt alle .md-Dateien als {dateiname: inhalt} zurück."""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    result: dict[str, str] = {}
    for fname in _FILE_HEADERS:
        p = MEMORY_DIR / fname
        if p.exists():
            content = p.read_text(encoding="utf-8").strip()
            if content:
                result[fname] = content
    return result


def interest_counts() -> dict[str, int]:
    """Gibt die rohen Interessen-Zähler zurück."""
    if not _INTEREST_COUNT_FILE.exists():
        return {}
    try:
        return json.loads(_INTEREST_COUNT_FILE.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def add_fact(fname: str, fact: str) -> bool:
    """Hängt einen Fakt manuell an eine Profil-Datei an. Gibt True zurück wenn geschrieben."""
    if fname not in _FILE_HEADERS:
        return False
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    _append_facts(fname, [fact])
    return True


def clear_file(fname: str) -> bool:
    """Leert eine Profil-Datei (nur den Inhalt, Header bleibt)."""
    if fname not in _FILE_HEADERS:
        return False
    p = MEMORY_DIR / fname
    if p.exists():
        p.write_text(_FILE_HEADERS[fname], encoding="utf-8")
    return True


def _model_extract(conversation: str, model_fn) -> None:
    """Fragt das Modell nach lernbaren Fakten aus dem Gespräch."""
    try:
        prompt = (
            "Analysiere dieses Gespräch und extrahiere maximal 7 kurze, konkrete Fakten "
            "über den Nutzer oder wie der Assistent sich verhalten soll.\n"
            "Format: eine Zeile pro Fakt, beginne jede Zeile mit einem dieser Präfixe:\n"
            "  USER:      — sachliche Info über den Nutzer (Name, Beruf, Ort)\n"
            "  VERHALTEN: — wie der Assistent sich verhalten soll\n"
            "  KORREKTUR: — was falsch war oder nicht mehr passieren soll\n"
            "  INTERESSE: — Themen oder Technologien die den Nutzer interessieren\n"
            "  SEELE:     — Werte, Träume, Lebensphilosophie, tiefe Motivationen\n\n"
            f"{conversation[-3000:]}\n\n"
            "Fakten (oder NICHTS wenn keine erkennbar):"
        )
        result = model_fn(prompt)
        if not result or "NICHTS" in result.upper():
            return

        buckets: dict[str, list[str]] = {
            "user.md": [], "behavior.md": [], "corrections.md": [],
            "interests.md": [], "soul.md": [],
        }
        _PREFIX_MAP = {
            "USER:": "user.md",
            "VERHALTEN:": "behavior.md",
            "KORREKTUR:": "corrections.md",
            "INTERESSE:": "interests.md",
            "SEELE:": "soul.md",
        }
        for line in result.splitlines():
            line = line.strip()
            for prefix, fname in _PREFIX_MAP.items():
                if line.upper().startswith(prefix):
                    fact = line[len(prefix):].strip()
                    if fact:
                        buckets[fname].append(fact)
                    break

        for fname, facts in buckets.items():
            if facts:
                _append_facts(fname, facts)
    except Exception:
        pass


def _append_facts(fname: str, facts: list[str]) -> None:
    """Hängt neue Fakten an eine .md-Datei an (doppelte überspringen)."""
    p = MEMORY_DIR / fname
    existing = p.read_text(encoding="utf-8") if p.exists() else ""

    new_lines: list[str] = []
    for fact in facts:
        if fact[:40].lower() not in existing.lower():
            # Zeilen die schon ein Bullet haben, nicht doppelt wrappen
            new_lines.append(fact if fact.startswith("- ") else f"- {fact}")

    if not new_lines:
        return

    ts = time.strftime("%Y-%m-%d")
    block = f"\n<!-- {ts} -->\n" + "\n".join(new_lines) + "\n"

    with open(p, "a", encoding="utf-8") as fh:
        if not existing:
            fh.write(_FILE_HEADERS.get(fname, ""))
        fh.write(block)

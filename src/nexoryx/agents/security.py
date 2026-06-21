"""Security-Agent mit Veto (Plan §6.3/§13).

Prüft risikoreiche Shell-Aktionen VOR der Ausführung. Hartes Veto bei
offensichtlich destruktiven/exfiltrierenden Mustern — unabhängig von der Rolle.
"""

from __future__ import annotations

import re

# Muster, die immer blockiert werden (Veto), auch für Admin.
_BLOCK = [
    r"\brm\s+-rf\s+/(?:\s|$)",          # rm -rf /
    r"\brm\s+-rf\s+~(?:/\s*)?$",         # rm -rf ~
    r":\(\)\s*\{.*\};\s*:",              # Fork-Bomb
    r"\bmkfs\b", r"\bdd\s+if=.*of=/dev/", r"\b>\s*/dev/sd",
    r"\bchmod\s+-R\s+777\s+/(?:\s|$)",
    r"\bcurl\b.*\|\s*(?:bash|sh)\b",     # curl|bash
    r"\bwget\b.*\|\s*(?:bash|sh)\b",
]
_BLOCK_RE = [re.compile(p) for p in _BLOCK]


def security_veto(command: str) -> str:
    """Leerer String = ok. Sonst die Begründung des Vetos."""
    for rx in _BLOCK_RE:
        if rx.search(command):
            return f"Security-Veto: Muster '{rx.pattern}' ist gesperrt."
    return ""

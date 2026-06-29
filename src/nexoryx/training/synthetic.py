"""Synthetische Trainingsbeispiele via lokalem Ollama-Modell.

Generiert Q&A-Paare ohne Benutzer-Konversation für den autotrain-Loop.
Das lokale Modell wird als Lehrer für seine eigene Verbesserung genutzt.
"""

from __future__ import annotations

import itertools
import time
from typing import Callable

from . import dataset

_SYSTEM = (
    "Du bist Nexoryx, ein präziser und hilfreicher KI-Assistent. "
    "Antworte immer direkt, konkret und auf Deutsch."
)

_POOL: dict[str, list[str]] = {
    "chat": [
        "Was ist der Unterschied zwischen Empathie und Mitgefühl?",
        "Erkläre, warum der Himmel blau ist.",
        "Nenne drei konkrete Tipps für besseren Schlaf.",
        "Was ist der Unterschied zwischen Energie und Leistung in der Physik?",
        "Erkläre das Konzept der kognitiven Dissonanz.",
        "Was ist der Unterschied zwischen einem Virus und einer Bakterie?",
        "Was bedeutet Occam's Razor?",
        "Erkläre kurz was Inflation ist und was sie verursacht.",
        "Was ist der Unterschied zwischen Moral und Ethik?",
        "Warum vergessen Menschen träume so schnell?",
    ],
    "coding": [
        "Schreibe eine Python-Funktion, die prüft ob eine Zahl eine Primzahl ist.",
        "Erkläre den Unterschied zwischen list und tuple in Python.",
        "Wie funktioniert eine HashMap intern?",
        "Was ist der Unterschied zwischen synchronem und asynchronem Code?",
        "Erkläre Rekursion mit einem einfachen Beispiel.",
        "Was ist der Unterschied zwischen '==' und 'is' in Python?",
        "Wie funktioniert ein binärer Suchbaum?",
        "Erkläre das Observer-Entwurfsmuster kurz.",
        "Was ist der Unterschied zwischen Stack und Heap?",
        "Erkläre Big-O-Notation an einem Beispiel.",
    ],
    "reasoning": [
        "Wenn alle A B sind und alle B C sind, sind dann alle A auch C? Erkläre.",
        "Was ist der Unterschied zwischen Induktion und Deduktion?",
        "Erkläre das Prisoner's Dilemma mit konkretem Beispiel.",
        "Was ist Opportunity Cost? Erkläre mit einem Beispiel.",
        "Was ist der Unterschied zwischen Korrelation und Kausalität?",
        "Erkläre den Sunk Cost Fallacy.",
        "Erkläre das Konzept der Falsifizierbarkeit nach Popper.",
        "Was ist das Trolley-Problem und was lehrt es über Ethik?",
        "Erkläre Occams Rasiermesser und wann man es anwendet.",
        "Was bedeutet es, wenn ein Argument 'schlüssig' ist?",
    ],
    "research": [
        "Was ist CRISPR-Cas9 und wofür wird es verwendet?",
        "Erkläre den Unterschied zwischen Machine Learning und Deep Learning.",
        "Wie funktioniert ein neuronales Netz auf hohem Niveau?",
        "Was ist Quantenverschränkung?",
        "Erkläre das Konzept des Reinforcement Learning.",
        "Was ist der Unterschied zwischen supervised und unsupervised Learning?",
        "Wie funktioniert GPS?",
        "Was ist Blockchain-Technologie und wie funktioniert sie?",
        "Was ist der Unterschied zwischen RAM und ROM?",
        "Erkläre wie ein Compiler funktioniert.",
    ],
    "action": [
        "Beschreibe Schritt für Schritt, wie man ein Python-Virtualenv erstellt.",
        "Wie installiert man Pakete mit pip und speichert sie in requirements.txt?",
        "Erkläre, wie man mit git einen neuen Branch erstellt und pusht.",
        "Wie erstellt man einen systemd-Service?",
        "Beschreibe wie man in Linux Dateirechte mit chmod verwaltet.",
        "Wie richtet man SSH-Key-Authentication ein?",
        "Erkläre wie man ein Docker-Image erstellt und startet.",
        "Wie setzt man eine einfache cron-Job-Regel auf?",
        "Wie findet man in Linux alle Dateien größer als 100 MB?",
        "Wie überprüft man in Python ob eine Datei existiert?",
    ],
}

# Flache Liste aller (task_type, question)-Paare in round-robin-Reihenfolge
# (erst alle chat[0], coding[0], ..., dann chat[1], coding[1], ..., usw.)
_ALL_TOPICS: list[tuple[str, str]] = []
_categories = list(_POOL.items())
_max_len = max(len(qs) for _, qs in _categories)
for _i in range(_max_len):
    for _task_type, _questions in _categories:
        if _i < len(_questions):
            _ALL_TOPICS.append((_task_type, _questions[_i]))

# Modulweiter Zyklus-Iterator: jeder generate_batch()-Aufruf macht genau dort
# weiter, wo der vorherige aufgehört hat — keine Wiederholungen über Runden.
_cycle = itertools.cycle(range(len(_ALL_TOPICS)))


# Templates für benutzerdefinierte Themengebiete
_TOPIC_TEMPLATES = [
    "Erkläre {topic} kurz und verständlich.",
    "Was sind die wichtigsten Konzepte bei {topic}?",
    "Nenne ein konkretes Beispiel für {topic}.",
    "Was sind häufige Fehler oder Missverständnisse bei {topic}?",
    "Wie funktioniert {topic} grundlegend?",
    "Warum ist {topic} wichtig oder relevant?",
    "Was ist der Unterschied zwischen {topic} und ähnlichen Konzepten?",
    "Was sind typische Anwendungsfälle für {topic}?",
]


def _task_type_from_topic(topic: str) -> str:
    """Ordnet ein Thema einem task_type zu."""
    t = topic.lower()
    if any(w in t for w in ("python", "java", "code", "script", "programmier",
                             "sql", "api", "git", "docker", "linux")):
        return "coding"
    if any(w in t for w in ("sicherheit", "security", "hack", "kryptograph",
                             "verschlüssel", "netzwerk", "exploit")):
        return "reasoning"
    if any(w in t for w in ("chat", "gespräch", "alltag", "emotion", "psycholog")):
        return "chat"
    if any(w in t for w in ("plan", "aufgabe", "schritt", "workflow", "prozess",
                             "anleitung", "howto")):
        return "action"
    return "research"


def generate_batch(
    model_tag: str,
    n: int = 10,
    *,
    custom_topics: list[str] | None = None,
    log_fn: Callable[[str], None] = print,
) -> int:
    """Generiert n synthetische Q&A-Paare via model_tag und speichert sie im Dataset.

    custom_topics: wenn angegeben, werden Fragen zu diesen Themen generiert
                   statt des eingebauten Standard-Pools.
    Gibt die Anzahl tatsächlich gespeicherter Beispiele zurück.
    """
    from ..router.base import ChatRequest
    from ..router.providers.ollama import OllamaProvider

    provider = OllamaProvider()
    saved = 0
    max_attempts = n * 4

    # Quelle: benutzerdefinierte Themen oder Standard-Pool
    if custom_topics:
        topic_items = [
            (_task_type_from_topic(topic), template.format(topic=topic))
            for topic in custom_topics
            for template in _TOPIC_TEMPLATES
        ]
        source = itertools.cycle(topic_items)
    else:
        source = None  # nutzt globalen _cycle auf _ALL_TOPICS

    for _ in range(max_attempts):
        if saved >= n:
            break

        if source is not None:
            task_type, question = next(source)
        else:
            idx = next(_cycle)
            task_type, question = _ALL_TOPICS[idx]

        prompt = (
            "Beantworte folgende Frage direkt und hilfreich in 2-6 Sätzen:\n\n"
            + question
        )
        req = ChatRequest(prompt=prompt, system=_SYSTEM, max_tokens=350)
        try:
            resp = provider.generate(req, model_tag)
            answer = resp.text.strip()
        except Exception as exc:
            log_fn(f"  Synthese-Fehler ({task_type}): {exc}")
            continue

        if len(answer) < 30:
            continue

        dataset.record_interaction(
            prompt=question,
            system=_SYSTEM,
            response=answer,
            provider="synthetic",
            model=model_tag,
            task_type=task_type,
            is_local=True,
        )
        saved += 1
        log_fn(f"  [{task_type}] {question[:55]}… ({len(answer)} Zeichen)")
        time.sleep(0.05)

    return saved

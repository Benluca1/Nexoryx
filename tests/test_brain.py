"""Tests für das Bootstrap-Brain (Task-Klassifikation)."""

from nexoryx.brain import classify
from nexoryx.router.providers.echo import EchoProvider
from nexoryx.router.base import ChatRequest


def test_trivial_greeting():
    r = classify("hallo")
    assert r.trivial and r.canned


def test_coding_intent():
    assert classify("Schreibe eine Python Funktion").task_type == "coding"


def test_reasoning_intent():
    assert classify("Warum ist der Himmel blau? Erkläre").task_type == "reasoning"


def test_default_chat():
    assert classify("Erzähl mir etwas Schönes").task_type == "chat"


def test_echo_provider_always_available():
    p = EchoProvider()
    assert p.available()
    resp = p.generate(ChatRequest(prompt="x"), "rule-fallback")
    assert "Nexoryx" in resp.text

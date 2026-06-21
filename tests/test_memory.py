"""Tests für den Multi-Layer-Speicher."""

import tempfile
from pathlib import Path

from nexoryx.memory import MemoryStore


def _store():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    return MemoryStore(Path(tmp.name))


def test_remember_and_recall():
    mem = _store()
    mem.remember("Der User programmiert in Python und mag Dark-Mode")
    hits = mem.recall("python")
    assert hits and "Python" in hits[0].text


def test_preferences():
    mem = _store()
    mem.set_preference("theme", "dark")
    assert mem.preferences().get("theme") == "dark"


def test_forget():
    mem = _store()
    mem.remember("temporäre Notiz über Kaffee")
    assert mem.forget("kaffee") == 1
    assert mem.recall("kaffee") == []

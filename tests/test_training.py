"""Tests für den Self-Improvement-Flywheel (Datenerfassung + House-Base)."""

import tempfile
from pathlib import Path

import nexoryx.training.dataset as ds
from nexoryx.platform.profile import Profile
from nexoryx.training.house import recommended_base


def _tmp_dataset(monkey_path: Path):
    ds.DATASET_DIR = monkey_path.parent
    ds.DATASET_PATH = monkey_path


def test_record_and_stats():
    with tempfile.TemporaryDirectory() as d:
        _tmp_dataset(Path(d) / "ds.jsonl")
        ds.record_interaction("frage", "", "antwort cloud", provider="anthropic",
                              model="claude-opus-4-8", task_type="chat", is_local=False)
        ds.record_interaction("frage2", "", "antwort lokal", provider="ollama",
                              model="x", task_type="coding", is_local=True)
        # Fallback wird NICHT erfasst
        ds.record_interaction("f", "", "x", provider="local-fallback",
                              model="rule", task_type="chat", is_local=True)
        st = ds.stats()
        assert st["total"] == 2
        assert st["teacher"] == 1  # nur die Cloud-Antwort


def test_export_teacher_only():
    with tempfile.TemporaryDirectory() as d:
        _tmp_dataset(Path(d) / "ds.jsonl")
        ds.record_interaction("a", "", "cloud", provider="openai", model="m",
                              task_type="chat", is_local=False)
        ds.record_interaction("b", "", "lokal", provider="ollama", model="m",
                              task_type="chat", is_local=True)
        out = Path(d) / "out.jsonl"
        assert ds.export_chatml(str(out), teacher_only=True) == 1


def test_select_examples_prefers_recent_and_dedupes():
    import importlib
    tr = importlib.import_module("nexoryx.training.train")
    ev = importlib.import_module("nexoryx.training.eval")

    with tempfile.TemporaryDirectory() as d:
        _tmp_dataset(Path(d) / "ds.jsonl")
        # 60 Teacher-Beispiele: alt (frage 000..) bis neu (frage 059..)
        for i in range(60):
            ds.record_interaction(
                f"frage nummer {i:03d}", "",
                f"ausreichend lange antwort nummer {i:03d}",
                provider="anthropic", model="m", task_type="chat",
                is_local=False,
            )
        # exaktes Duplikat des neuesten -> darf nur einmal vorkommen
        ds.record_interaction(
            "frage nummer 059", "", "ausreichend lange antwort nummer 059",
            provider="anthropic", model="m", task_type="chat", is_local=False,
        )

        selected = tr._select_examples(max_n=30)
        assert len(selected) == 30

        users = [tr._first(ex, "user") for ex in selected]
        # keine Duplikate
        assert len(set(users)) == len(users)
        # Trainingsmenge meidet den Holdout
        holdout = ev.holdout_keys()
        sel_keys = {(u.strip().lower(),
                     ("ausreichend lange antwort " + u.split()[-1]).lower())
                    for u in users}
        assert sel_keys.isdisjoint(holdout)
        # Flywheel-Kern: neueste (Nicht-Holdout-)Beispiele sind drin, älteste nicht
        def is_holdout(idx):
            return ("frage nummer %03d" % idx, "ausreichend lange antwort nummer %03d" % idx) and (
                ev._stable_hash("frage nummer %03d" % idx) % ev.HOLDOUT_DIVISOR == 0)
        newest_non_holdout = next(i for i in range(59, -1, -1) if not is_holdout(i))
        oldest_non_holdout = next(i for i in range(0, 60) if not is_holdout(i))
        assert "frage nummer %03d" % newest_non_holdout in users
        assert "frage nummer %03d" % oldest_non_holdout not in users


def test_select_examples_filters_low_quality():
    import importlib; tr = importlib.import_module("nexoryx.training.train")

    with tempfile.TemporaryDirectory() as d:
        _tmp_dataset(Path(d) / "ds.jsonl")
        ds.record_interaction("gute frage hier", "",
                              "eine ausreichend lange gute antwort",
                              provider="anthropic", model="m",
                              task_type="chat", is_local=False)
        ds.record_interaction("x", "", "ok",  # zu kurz -> raus
                              provider="anthropic", model="m",
                              task_type="chat", is_local=False)
        selected = tr._select_examples(max_n=30)
        assert len(selected) == 1


def test_token_f1_basic():
    import importlib
    ev = importlib.import_module("nexoryx.training.eval")
    assert ev._token_f1("hallo welt", "hallo welt") == 1.0
    assert ev._token_f1("", "x") == 0.0
    assert 0.0 < ev._token_f1("hallo welt heute", "hallo welt") < 1.0


def test_holdout_is_deterministic_and_disjoint_from_training():
    import importlib
    ev = importlib.import_module("nexoryx.training.eval")
    tr = importlib.import_module("nexoryx.training.train")
    with tempfile.TemporaryDirectory() as d:
        _tmp_dataset(Path(d) / "ds.jsonl")
        for i in range(40):
            ds.record_interaction(
                f"eindeutige frage {i:03d}", "",
                f"eine ausreichend lange antwort nummer {i:03d}",
                provider="anthropic", model="m", task_type="chat",
                is_local=False,
            )
        keys = ev.holdout_keys()
        assert keys  # mind. ein Holdout-Beispiel
        assert ev.holdout_keys() == keys  # deterministisch
        # Trainingsauswahl enthält KEIN Holdout-Beispiel
        selected = tr._select_examples(max_n=30)
        sel_keys = {(tr._first(e, "user").strip().lower(),
                     tr._first(e, "assistant").strip().lower()) for e in selected}
        assert sel_keys.isdisjoint(keys)


def test_gate_promotes_better_and_rejects_worse(monkeypatch):
    import importlib
    ev = importlib.import_module("nexoryx.training.eval")
    with tempfile.TemporaryDirectory() as d:
        _tmp_dataset(Path(d) / "ds.jsonl")
        for i in range(40):
            ds.record_interaction(
                f"frage {i:03d}", "", f"die korrekte referenzantwort {i:03d}",
                provider="anthropic", model="m", task_type="chat", is_local=False,
            )

        # Kandidat trifft die Referenz, Baseline antwortet Müll → Promotion
        def good_or_bad(model_tag, prompt, system):
            if model_tag == "cand":
                return "die korrekte referenzantwort"
            return "völlig unpassender text quark"
        monkeypatch.setattr(ev, "_generate", good_or_bad)
        v = ev.gate("cand", "inc")
        assert v["promote"] is True
        assert v["candidate_score"] >= v["incumbent_score"]

        # Umgekehrt: Kandidat schlechter → Rollback
        def bad_or_good(model_tag, prompt, system):
            if model_tag == "cand":
                return "völlig unpassender text quark"
            return "die korrekte referenzantwort"
        monkeypatch.setattr(ev, "_generate", bad_or_good)
        v2 = ev.gate("cand", "inc")
        assert v2["promote"] is False


def test_gate_skips_eval_with_tiny_holdout(monkeypatch):
    import importlib
    ev = importlib.import_module("nexoryx.training.eval")
    with tempfile.TemporaryDirectory() as d:
        _tmp_dataset(Path(d) / "ds.jsonl")
        ds.record_interaction("nur eine frage", "", "nur eine lange antwort hier",
                              provider="anthropic", model="m",
                              task_type="chat", is_local=False)
        called = {"n": 0}

        def _spy(*a, **k):
            called["n"] += 1
            return ""
        monkeypatch.setattr(ev, "_generate", _spy)
        v = ev.gate("cand", "inc")
        # zu wenig Holdout → Promotion ohne Modell-Inferenz
        assert v["promote"] is True
        assert called["n"] == 0


def test_recommended_base_per_profile():
    p = Profile("ultra_lite", False, False, 1, "")
    base = recommended_base(p)
    assert "ollama" in base and "hf" in base
    assert recommended_base(Profile("pro", True, True, 8, ""))["ollama"] != base["ollama"]

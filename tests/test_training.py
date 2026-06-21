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


def test_recommended_base_per_profile():
    p = Profile("ultra_lite", False, False, 1, "")
    base = recommended_base(p)
    assert "ollama" in base and "hf" in base
    assert recommended_base(Profile("pro", True, True, 8, ""))["ollama"] != base["ollama"]

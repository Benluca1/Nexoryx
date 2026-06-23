"""Training des hauseigenen Modells aus den erfassten Daten (Plan §3.3).

Primärer Weg — Ollama Modelfile (kein GPU, kein Download, sofort):
  1. Top-N Trainingsbeispiele aus dem Dataset wählen (Teacher/Cloud bevorzugt)
  2. Ollama Modelfile schreiben: FROM qwen2.5:0.5b + SYSTEM + MESSAGE-Paare
  3. `ollama create nexoryx-house-vN -f Modelfile` ausführen
  4. Eval-Gate (eval.py): vN gegen das bisherige Modell auf Holdout testen
  5. Nur bei Bestehen: Config aktualisieren (house_base = vN, house_trained = True);
     sonst Rollback — vN wird verworfen, altes Modell bleibt aktiv
  → Nexoryx nutzt danach automatisch das beste Modell

Sekundärer Weg — LoRA Fine-Tuning via HuggingFace (GPU empfohlen):
  Nur wenn Ollama nicht verfügbar. Generiert ein Trainings-Skript.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from ..platform import choose_profile, detect
from ..platform import config as cfg_mod
from . import dataset
from .eval import _first
from .house import HOUSE_BASE, HOUSE_HF

MIN_EXAMPLES = 20   # Ollama-Weg braucht weniger als LoRA
MIN_LORA     = 50   # LoRA-Weg braucht mehr Daten


def _deps_available() -> list[str]:
    missing = []
    for mod in ("torch", "transformers", "peft", "datasets"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    return missing


def _ollama_available() -> bool:
    try:
        r = subprocess.run(["ollama", "list"], capture_output=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


def train_report() -> dict:
    cfg = cfg_mod.load()
    st = dataset.stats()
    return {
        "dataset": st,
        "house_base": cfg.house_base or HOUSE_BASE,
        "house_hf": HOUSE_HF,
        "house_trained": cfg.house_trained,
        "house_version": cfg.house_version,
        "deps_missing": _deps_available(),
        "ollama_available": _ollama_available(),
        "ready": st["total"] >= MIN_EXAMPLES,
    }


# ── Ollama-Modelfile-Weg ──────────────────────────────────────────────────────

def _quality_ok(ex: dict) -> bool:
    """Filtert leere, zu kurze oder offensichtlich fehlerhafte Beispiele aus."""
    user = _first(ex, "user").strip()
    answer = _first(ex, "assistant").strip()
    if len(user) < 3 or len(answer) < 15:
        return False
    low = answer.lower()
    if low.startswith(("fehler", "error:", "entschuldigung, ich kann")):
        return False
    return True


def _diversify(examples: list[dict], limit: int) -> list[dict]:
    """Round-Robin über task_type → thematische Vielfalt im Few-Shot-Set.

    Erwartet bereits nach Aktualität sortierte Eingabe; die Bucket-Reihenfolge
    bleibt dadurch erhalten (neueste zuerst).
    """
    buckets: dict[str, list[dict]] = {}
    for ex in examples:
        buckets.setdefault(ex.get("task_type", "chat"), []).append(ex)
    out: list[dict] = []
    while len(out) < limit and any(buckets.values()):
        for key in list(buckets):
            if buckets[key]:
                out.append(buckets[key].pop(0))
                if len(out) >= limit:
                    break
    return out


def _select_examples(max_n: int = 30) -> list[dict]:
    """Wählt die besten Trainingsbeispiele.

    Wichtig fürs Flywheel: die NEUESTEN Daten müssen einfließen, sonst bäckt
    jedes Retraining dieselben alten Beispiele ein. Dedupliziert, filtert
    Müll heraus, bevorzugt Teacher (Cloud), sorgt für task_type-Vielfalt und
    begrenzt synthetische Beispiele auf max. 20 %.
    """
    from . import eval as eval_gate

    seen: set[tuple[str, str]] = set()
    teacher: list[dict] = []
    local: list[dict] = []
    synthetic: list[dict] = []
    for ex in dataset.iter_examples():
        if not _quality_ok(ex):
            continue
        if eval_gate._is_holdout(ex):
            continue
        key = (_first(ex, "user").strip().lower(),
               _first(ex, "assistant").strip().lower())
        if key in seen:
            continue
        seen.add(key)
        if ex.get("provider") == "synthetic":
            synthetic.append(ex)
        elif ex.get("teacher"):
            teacher.append(ex)
        else:
            local.append(ex)

    # neueste zuerst — der Kern des Fixes
    for lst in (teacher, local, synthetic):
        lst.sort(key=lambda e: e.get("ts", 0.0), reverse=True)

    selected = _diversify(teacher, max_n)
    if len(selected) < max_n:
        selected += _diversify(local, max_n - len(selected))
    if len(selected) < max_n and synthetic:
        synth_cap = max(1, max_n // 5)
        room = min(synth_cap, max_n - len(selected))
        selected += synthetic[:room]
    return selected[:max_n]


def _build_modelfile(base_tag: str, examples: list[dict]) -> str:
    def _safe(text: str, limit: int) -> str:
        return text.strip().replace('"""', '"\\""')[:limit]

    lines = [
        f"FROM {base_tag}",
        "",
        'SYSTEM """Du bist Nexoryx, ein präziser und kompetenter KI-Assistent. '
        "Antworte immer auf Deutsch. Sei direkt und hilfreich. "
        'Nutze verfügbare Tools wenn nötig."""',
        "",
    ]
    for ex in examples:
        for m in ex.get("messages", []):
            role = m.get("role", "")
            content = m.get("content", "").strip()
            if role == "user" and content:
                lines.append(f'MESSAGE user """{_safe(content, 500)}"""')
            elif role == "assistant" and content:
                lines.append(f'MESSAGE assistant """{_safe(content, 800)}"""')
    return "\n".join(lines)


def _train_ollama(base_tag: str, version: int) -> dict:
    """Erstellt nexoryx-house-vN via Ollama Modelfile."""
    import socket
    model_name = f"nexoryx-house-v{version}"
    examples = _select_examples(max_n=30)
    modelfile_content = _build_modelfile(base_tag, examples)

    # Modelfile ins Repo schreiben → wird beim Push mitgenommen
    device = socket.gethostname().lower()[:20]
    repo_mf_dir = Path(__file__).resolve().parents[4] / "training" / "modelfiles"
    repo_mf_dir.mkdir(parents=True, exist_ok=True)
    repo_mf_path = repo_mf_dir / f"{device}_v{version}.modelfile"
    repo_mf_path.write_text(modelfile_content, encoding="utf-8")

    # Auch lokal für Ollama
    local_mf_dir = Path.home() / ".nexoryx" / "auto_training"
    local_mf_dir.mkdir(parents=True, exist_ok=True)
    mf_path = local_mf_dir / "Modelfile"
    mf_path.write_text(modelfile_content, encoding="utf-8")

    result = subprocess.run(
        ["ollama", "create", model_name, "-f", str(mf_path)],
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout).strip()[:400]
        return {"action": "failed", "error": err}

    # Alte Versionen aufräumen — nur die letzten beiden behalten (Platz sparen)
    _cleanup_old_versions(keep_from=version - 1)

    return {
        "action": "trained",
        "model_name": model_name,
        "modelfile": str(mf_path),
        "examples_used": len(examples),
    }


def _ollama_rm(tag: str) -> None:
    try:
        subprocess.run(["ollama", "rm", tag], capture_output=True, timeout=15)
    except Exception:
        pass


def _cleanup_old_versions(keep_from: int) -> None:
    """Entfernt nexoryx-house-vN-Modelle älter als `keep_from` aus Ollama."""
    for old in range(max(0, keep_from - 1), 0, -1):
        _ollama_rm(f"nexoryx-house-v{old}")


# ── LoRA-Skript-Weg (Fallback) ────────────────────────────────────────────────

def _write_lora_script(repo_root: Path, hf_base: str, data_path: str) -> Path:
    repo_root.mkdir(parents=True, exist_ok=True)
    script = repo_root / "finetune_house.py"
    script.write_text(
        f'''#!/usr/bin/env python3
"""Nexoryx House-Model LoRA-Finetune (auto-generiert).

Voraussetzungen (GPU empfohlen):
    pip install torch transformers peft datasets trl accelerate
Ausführen:
    python finetune_house.py
Ergebnis: LoRA-Adapter in ./house-adapter
"""
from datasets import load_dataset
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import LoraConfig
from trl import SFTTrainer, SFTConfig

BASE = "{hf_base}"
DATA = "{data_path}"

tok = AutoTokenizer.from_pretrained(BASE)
model = AutoModelForCausalLM.from_pretrained(BASE, device_map="auto")
ds = load_dataset("json", data_files=DATA, split="train")

def fmt(ex):
    return {{"text": tok.apply_chat_template(ex["messages"], tokenize=False)}}

ds = ds.map(fmt)
peft_cfg = LoraConfig(r=16, lora_alpha=32, lora_dropout=0.05, task_type="CAUSAL_LM")
trainer = SFTTrainer(
    model=model, train_dataset=ds, peft_config=peft_cfg,
    args=SFTConfig(output_dir="house-adapter", num_train_epochs=2,
                   per_device_train_batch_size=1, gradient_accumulation_steps=8,
                   learning_rate=2e-4, logging_steps=10, save_strategy="epoch"),
)
trainer.train()
trainer.save_model("house-adapter")
print("Fertig: ./house-adapter")
''',
        encoding="utf-8",
    )
    return script


# ── Haupt-Einstieg ────────────────────────────────────────────────────────────

def train(repo_root: Path | None = None) -> dict:
    """Training auslösen. Gibt einen Bericht zurück."""
    cfg = cfg_mod.load()
    st = dataset.stats()
    base_tag = HOUSE_BASE   # immer qwen2.5:0.5b
    report: dict = {"action": "", "base": base_tag, "stats": st}

    if st["total"] < MIN_EXAMPLES:
        report["action"] = "skipped"
        report["reason"] = (
            f"Zu wenige Beispiele ({st['total']}/{MIN_EXAMPLES}). "
            "Nutze Nexoryx weiter — jede Antwort sammelt Daten."
        )
        return report

    # ── Primär: Ollama Modelfile (kein GPU nötig) ──────────────────────────
    if _ollama_available():
        next_version = cfg.house_version + 1
        result = _train_ollama(base_tag, next_version)
        report.update(result)
        if result["action"] == "trained":
            candidate = result["model_name"]
            incumbent = cfg.house_base or base_tag

            # Eval-Gate (Plan §3.3.5): nur aktivieren, wenn nicht schlechter
            try:
                from . import eval as eval_gate
                verdict = eval_gate.gate(candidate, incumbent)
            except Exception as exc:  # Eval-Infra darf Training nie blockieren
                verdict = {"promote": False, "reason": f"Eval-Fehler ({exc}) — Rollback",
                           "candidate_score": None, "incumbent_score": None}
            report["eval"] = verdict

            if verdict["promote"]:
                cfg.house_base = candidate
                cfg.house_trained = True
                cfg.house_version = next_version
                cfg_mod.save(cfg)
                report["house_version"] = next_version
            else:
                # Rollback: Kandidat verwerfen, bisheriges Modell behalten
                _ollama_rm(candidate)
                report["action"] = "rejected"
                report["kept"] = incumbent
                report["house_version"] = cfg.house_version
        return report

    # ── Fallback: LoRA-Skript generieren (GPU-Pfad) ────────────────────────
    if st["total"] < MIN_LORA:
        report["action"] = "skipped"
        report["reason"] = (
            f"Ollama nicht verfügbar und zu wenige Beispiele für LoRA "
            f"({st['total']}/{MIN_LORA}). Ollama installieren oder mehr Daten sammeln."
        )
        return report

    out_dir = repo_root or Path.cwd() / "training"
    out_dir.mkdir(parents=True, exist_ok=True)
    data_path = out_dir / "dataset_chatml.jsonl"
    n = dataset.export_chatml(
        str(data_path),
        teacher_only=st["teacher"] >= MIN_LORA,
    )
    report["exported"] = {"path": str(data_path), "lines": n}

    missing = _deps_available()
    script = _write_lora_script(out_dir, HOUSE_HF, str(data_path))
    report["action"] = "script_generated"
    report["script"] = str(script)
    report["deps_missing"] = missing
    report["instructions"] = (
        f"pip install {' '.join(missing + ['trl', 'accelerate'])}  &&  python {script}"
        if missing else f"python {script}"
    )
    return report

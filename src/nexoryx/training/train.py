"""Training des hauseigenen Modells aus den erfassten Daten (Plan §3.3).

Distillation/Finetune: nutzt bevorzugt die `teacher`-Beispiele (Cloud-Antworten)
als Lernsignal für das hardware-gewählte Basismodell.

- Sind torch+transformers+peft+trl installiert UND eine GPU/genug RAM da:
  echtes LoRA-Finetuning (ressourcenintensiv — bewusst nicht im Lite-Kern).
- Sonst: exportiert den Datensatz + erzeugt ein lauffähiges Trainings-Skript
  und erklärt die nächsten Schritte. Kein Fake-Erfolg.
"""

from __future__ import annotations

from pathlib import Path

from ..platform import choose_profile, detect
from ..platform import config as cfg_mod
from . import dataset
from .house import recommended_base

MIN_EXAMPLES = 50  # Eval-Gate-Untergrenze; darunter lohnt Training nicht


def _deps_available() -> list[str]:
    missing = []
    for mod in ("torch", "transformers", "peft", "datasets"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    return missing


def train_report() -> dict:
    cfg = cfg_mod.load()
    hw = detect()
    base = recommended_base(choose_profile(hw), hw)
    st = dataset.stats()
    return {
        "dataset": st,
        "house_base": cfg.house_base or base["ollama"],
        "recommended_base": base,
        "house_trained": cfg.house_trained,
        "house_version": cfg.house_version,
        "deps_missing": _deps_available(),
        "ready": st["total"] >= MIN_EXAMPLES,
    }


def _write_script(repo_root: Path, hf_base: str, data_path: str) -> Path:
    repo_root.mkdir(parents=True, exist_ok=True)
    script = repo_root / "finetune_house.py"
    script.write_text(
        f'''#!/usr/bin/env python3
"""Nexoryx House-Model LoRA-Finetune (auto-generiert).

Voraussetzungen (GPU empfohlen):
    pip install torch transformers peft datasets trl accelerate
Ausführen:
    python finetune_house.py
Ergebnis: LoRA-Adapter in ./house-adapter  (danach GGUF-Export via llama.cpp,
dann in Ollama registrieren und `nexoryx config set house_trained true`).
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


def train(repo_root: Path | None = None) -> dict:
    """Training auslösen. Gibt einen Bericht zurück (was passiert ist)."""
    cfg = cfg_mod.load()
    hw = detect()
    base = recommended_base(choose_profile(hw), hw)
    st = dataset.stats()
    report = {"action": "", "base": base, "stats": st}

    if st["total"] < MIN_EXAMPLES:
        report["action"] = "skipped"
        report["reason"] = (
            f"Zu wenige Beispiele ({st['total']}/{MIN_EXAMPLES}). "
            "Nutze Nexoryx weiter (jede Antwort sammelt Daten), dann erneut."
        )
        return report

    # Datensatz exportieren (bevorzugt Teacher/Cloud-Beispiele).
    out_dir = (repo_root or Path.cwd() / "training")
    out_dir.mkdir(parents=True, exist_ok=True)
    data_path = out_dir / "dataset_chatml.jsonl"
    n = dataset.export_chatml(str(data_path), teacher_only=st["teacher"] >= MIN_EXAMPLES)
    report["exported"] = {"path": str(data_path), "lines": n}

    missing = _deps_available()
    if missing:
        script = _write_script(out_dir, base["hf"], str(data_path))
        report["action"] = "script_generated"
        report["script"] = str(script)
        report["deps_missing"] = missing
        report["instructions"] = (
            f"pip install {' '.join(missing)} trl accelerate  &&  python {script}"
        )
        return report

    # Deps vorhanden → echtes Training (auf geeigneter Hardware).
    try:
        script = _write_script(out_dir, base["hf"], str(data_path))
        import runpy
        runpy.run_path(str(script), run_name="__main__")
        cfg.house_trained = True
        cfg.house_version += 1
        cfg_mod.save(cfg)
        report["action"] = "trained"
        report["house_version"] = cfg.house_version
    except Exception as exc:  # noqa: BLE001
        report["action"] = "failed"
        report["error"] = str(exc)
    return report

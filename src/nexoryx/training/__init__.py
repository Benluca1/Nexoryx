"""Self-Improvement-Flywheel (Plan §3.4/§13).

Am Anfang nutzt Nexoryx ein hardware-passend gewähltes BESTEHENDES Modell
(`house`). Jede Antwort — egal ob Cloud oder lokal — wird als Trainingsdatum
erfasst (Cloud = Teacher für Distillation). `train` macht daraus das hauseigene
Modell.
"""

from .dataset import record_interaction, stats, export_chatml, DATASET_PATH
from .house import recommended_base, HOUSE_BASES
from .train import train, train_report

__all__ = [
    "record_interaction", "stats", "export_chatml", "DATASET_PATH",
    "recommended_base", "HOUSE_BASES", "train", "train_report",
]

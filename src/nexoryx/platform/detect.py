"""Hardware-Erkennung — CPU, RAM, GPU/VRAM, OS, freier Speicher.

Bewusst nur Standardbibliothek, damit `nexoryx doctor` auf jeder frischen
Maschine ohne `pip install` läuft. Externe Tools (nvidia-smi, lscpu, lspci)
werden best-effort genutzt; fehlen sie, gibt es konservative Fallbacks.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass, asdict, field


@dataclass
class GPU:
    vendor: str  # "nvidia" | "amd" | "intel" | "apple" | "none"
    name: str = ""
    vram_mb: int = 0  # 0 = unbekannt / keine dedizierte VRAM


@dataclass
class Hardware:
    os_name: str
    os_version: str
    arch: str
    cpu_model: str
    cpu_cores_physical: int
    cpu_cores_logical: int
    ram_mb: int
    disk_free_mb: int
    gpu: GPU = field(default_factory=lambda: GPU("none"))

    @property
    def vram_mb(self) -> int:
        return self.gpu.vram_mb

    def as_dict(self) -> dict:
        d = asdict(self)
        d["vram_mb"] = self.vram_mb
        return d


def _run(cmd: list[str], timeout: float = 4.0) -> str:
    """Ein externes Kommando best-effort ausführen; leer bei Fehler."""
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _cpu_model() -> str:
    system = platform.system()
    if system == "Linux":
        try:
            with open("/proc/cpuinfo", encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    if line.lower().startswith("model name"):
                        return line.split(":", 1)[1].strip()
        except OSError:
            pass
        lscpu = _run(["lscpu"])
        m = re.search(r"Model name:\s*(.+)", lscpu)
        if m:
            return m.group(1).strip()
    elif system == "Darwin":
        name = _run(["sysctl", "-n", "machdep.cpu.brand_string"])
        if name:
            return name
    elif system == "Windows":
        name = os.environ.get("PROCESSOR_IDENTIFIER", "")
        if name:
            return name
    return platform.processor() or "Unknown CPU"


def _cpu_cores() -> tuple[int, int]:
    logical = os.cpu_count() or 1
    physical = logical
    system = platform.system()
    if system == "Linux":
        lscpu = _run(["lscpu"])
        sockets = re.search(r"Socket\(s\):\s*(\d+)", lscpu)
        per_socket = re.search(r"Core\(s\) per socket:\s*(\d+)", lscpu)
        if sockets and per_socket:
            physical = int(sockets.group(1)) * int(per_socket.group(1))
    return physical, logical


def _ram_mb() -> int:
    # Bevorzugt POSIX sysconf (stdlib), sonst /proc, sonst Fallback.
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        if pages > 0 and page_size > 0:
            return int(pages * page_size / (1024 * 1024))
    except (ValueError, OSError, AttributeError):
        pass
    if platform.system() == "Darwin":
        out = _run(["sysctl", "-n", "hw.memsize"])
        if out.isdigit():
            return int(int(out) / (1024 * 1024))
    return 0


def _disk_free_mb(path: str | None = None) -> int:
    target = path or os.path.expanduser("~")
    try:
        usage = shutil.disk_usage(target)
        return int(usage.free / (1024 * 1024))
    except OSError:
        return 0


def _detect_gpu() -> GPU:
    # 1) NVIDIA — am verlässlichsten via nvidia-smi.
    if shutil.which("nvidia-smi"):
        out = _run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
            ]
        )
        if out:
            first = out.splitlines()[0]
            parts = [p.strip() for p in first.split(",")]
            name = parts[0] if parts else "NVIDIA GPU"
            vram = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
            return GPU("nvidia", name, vram)

    # 2) Apple Silicon — unified memory, keine separate VRAM-Zahl.
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        return GPU("apple", "Apple Silicon GPU", 0)

    # 3) AMD/Intel via lspci (Linux) — Vendor erkennen, VRAM meist unbekannt.
    if platform.system() == "Linux" and shutil.which("lspci"):
        lspci = _run(["lspci"]).lower()
        for line in lspci.splitlines():
            if "vga" in line or "3d controller" in line or "display" in line:
                if "nvidia" in line:
                    return GPU("nvidia", line.split(":")[-1].strip(), 0)
                if "amd" in line or "radeon" in line or "advanced micro" in line:
                    return GPU("amd", line.split(":")[-1].strip(), 0)
                if "intel" in line:
                    return GPU("intel", line.split(":")[-1].strip(), 0)

    return GPU("none")


def detect() -> Hardware:
    """Vollständige Hardware-Erkennung. Robust, niemals werfend."""
    physical, logical = _cpu_cores()
    return Hardware(
        os_name=platform.system() or "Unknown",
        os_version=platform.release() or "",
        arch=platform.machine() or "",
        cpu_model=_cpu_model(),
        cpu_cores_physical=physical,
        cpu_cores_logical=logical,
        ram_mb=_ram_mb(),
        disk_free_mb=_disk_free_mb(),
        gpu=_detect_gpu(),
    )

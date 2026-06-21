"""Sandbox-Ausführung für Shell-Kommandos (Plan §7).

Defense in Depth, abgestuft nach Verfügbarkeit:
  1. bubblewrap (`bwrap`) — Namespace-Isolation, falls vorhanden
  2. firejail — sonst, falls vorhanden
  3. Fallback: eingeschränkter Subprozess mit cwd-Jail, Timeout, Output-Limit

Docker-Variante ist im Plan vorgesehen; hier der zero-dependency-Pfad.
"""

from __future__ import annotations

import shutil
import subprocess

DEFAULT_TIMEOUT = 30
MAX_OUTPUT = 20_000


def _wrap(cmd: str, cwd: str) -> list[str]:
    if shutil.which("bwrap"):
        return [
            "bwrap", "--ro-bind", "/usr", "/usr", "--ro-bind", "/bin", "/bin",
            "--ro-bind", "/lib", "/lib", "--ro-bind", "/lib64", "/lib64",
            "--proc", "/proc", "--dev", "/dev", "--unshare-net",
            "--bind", cwd, cwd, "--chdir", cwd,
            "bash", "-lc", cmd,
        ]
    if shutil.which("firejail"):
        return ["firejail", "--quiet", "--net=none", f"--private={cwd}",
                "bash", "-lc", cmd]
    return ["bash", "-lc", cmd]


def run_sandboxed(cmd: str, cwd: str, timeout: int = DEFAULT_TIMEOUT) -> tuple[int, str, str, str]:
    """Gibt (returncode, stdout, stderr, sandbox_kind) zurück."""
    kind = ("bwrap" if shutil.which("bwrap")
            else "firejail" if shutil.which("firejail") else "subprocess")
    try:
        proc = subprocess.run(
            _wrap(cmd, cwd), cwd=cwd, capture_output=True, text=True,
            timeout=timeout, check=False,
        )
        out = proc.stdout[:MAX_OUTPUT]
        err = proc.stderr[:MAX_OUTPUT]
        return proc.returncode, out, err, kind
    except subprocess.TimeoutExpired:
        return 124, "", f"Timeout nach {timeout}s", kind
    except OSError as exc:
        return 1, "", str(exc), kind

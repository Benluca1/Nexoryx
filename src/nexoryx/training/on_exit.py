"""On-Exit-Hook: Training + Trainingsdaten + Chat + Persona-Upload nach Sitzungsende.

Laeuft nach dem Haupt-Loop -- wenn der Nutzer `nex` beendet:
1. Chat-Verlauf als Markdown in users/<username>/chats/ speichern
2. Persona-MD-Dateien in users/<username>/persona/ spiegeln
3. Trainingsdaten gerätespezifisch in training/data/ exportieren
4. Wenn genug Daten: Training ausloesen / Skript erzeugen
5. Via Git-Push zu GitHub hochladen (PAT aus ~/.nexoryx/secrets/github_pat
   oder Server-Relay -- funktioniert auf JEDEM Geraet im LAN)

Gerätespezifische JSONL-Dateien vermeiden Merge-Konflikte wenn mehrere
Geraete gleichzeitig pushen.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
from pathlib import Path

from .dataset import DATASET_PATH, stats, export_chatml
from ..platform.config import CONFIG_DIR

REPO_ROOT       = Path(__file__).resolve().parents[3]
TRAINING_DIR    = REPO_ROOT / "training"
TRAINING_DATA   = TRAINING_DIR / "data"
USERS_DIR       = REPO_ROOT / "users"
MEMORY_DIR      = CONFIG_DIR / "memory"
SECRETS_DIR     = CONFIG_DIR / "secrets"
PAT_FILE        = SECRETS_DIR / "github_pat"

MIN_NEW_FOR_UPLOAD = 1
MIN_FOR_TRAINING   = 20

SERVER_RELAY_URL   = "http://192.168.13.100:3008/training/upload"
SERVER_SECRET_FILE = CONFIG_DIR / "secrets" / "server-secret"


def _device_id() -> str:
    raw = socket.gethostname().lower()
    clean = "".join(c if c.isalnum() or c == "-" else "-" for c in raw)[:30]
    return clean or "device"


def get_username() -> str:
    """Liest den Nutzernamen aus user.md (falls bekannt), sonst Systemnutzer."""
    user_md = MEMORY_DIR / "user.md"
    if user_md.exists():
        try:
            content = user_md.read_text(encoding="utf-8")
            for pattern in (
                r"(?:ich hei[sS]e|mein name ist)[:\s]+([A-Za-zÄÖÜäöüß]{2,30})",
                r"\*\*Name\*\*[:\s]+([A-Za-zÄÖÜäöüß]{2,30})",
                r"^[-*]\s*(?:Name|Vorname)[:\s]+([A-Za-zÄÖÜäöüß]{2,30})",
            ):
                m = re.search(pattern, content, re.IGNORECASE | re.MULTILINE)
                if m:
                    return _safe_slug(m.group(1).strip())
        except OSError:
            pass
    for env in ("USER", "USERNAME", "LOGNAME"):
        val = os.environ.get(env, "").strip()
        if val:
            return _safe_slug(val)
    return _device_id()


def _safe_slug(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]", "-", name).lower().strip("-")[:30]
    return slug or "user"


def _save_chat_md(username: str, history: list) -> "Path | None":
    """Speichert Chat-Verlauf als Markdown unter users/<username>/chats/."""
    if not history:
        return None
    import time
    ts = time.strftime("%Y-%m-%d_%H-%M")
    chat_dir = USERS_DIR / username / "chats"
    chat_dir.mkdir(parents=True, exist_ok=True)
    dest = chat_dir / f"{ts}.md"
    lines = [f"# Chat {ts.replace('_', ' ')}\n\n"]
    for entry in history:
        if entry.startswith("User"):
            lines.append(f"\n**{entry}**\n\n")
        else:
            lines.append(f"{entry}\n\n")
    dest.write_text("".join(lines), encoding="utf-8")
    return dest


def _mirror_persona(username: str) -> None:
    """Spiegelt Persona-MD-Dateien nach users/<username>/persona/."""
    if not MEMORY_DIR.exists():
        return
    persona_dir = USERS_DIR / username / "persona"
    persona_dir.mkdir(parents=True, exist_ok=True)
    for md in MEMORY_DIR.glob("*.md"):
        shutil.copy2(md, persona_dir / md.name)


def run(console=None, silent: bool = False, history=None, username=None) -> dict:
    """Haupt-Einstieg -- wird nach dem Schliessen der TUI aufgerufen."""
    report: dict = {"uploaded": False, "trained": False, "errors": []}

    def log(msg: str) -> None:
        if silent:
            return
        if console:
            console.print(f"  [dim]{msg}[/dim]")
        else:
            print(f"  {msg}")

    if username is None:
        username = get_username()

    st = stats()
    data_file = None

    # 1. Chat-Verlauf sichern
    if history:
        try:
            chat_file = _save_chat_md(username, history)
            if chat_file:
                log(f"Chat: users/{username}/chats/{chat_file.name}")
                report["chat_file"] = str(chat_file)
        except Exception as exc:
            report["errors"].append(f"Chat-Export: {exc}")

    # 2. Persona-Dateien spiegeln
    try:
        _mirror_persona(username)
        log(f"Persona: users/{username}/persona/")
    except Exception as exc:
        report["errors"].append(f"Persona: {exc}")

    # 3. Trainingsdaten exportieren
    if DATASET_PATH.exists() and st["total"] >= MIN_NEW_FOR_UPLOAD:
        try:
            TRAINING_DATA.mkdir(parents=True, exist_ok=True)
            device = _device_id()
            data_file = TRAINING_DATA / f"{username}-{device}.jsonl"
            n = export_chatml(str(data_file))
            log(f"Training: {n} Beispiele → training/data/{data_file.name}")
            report["examples"] = n
        except Exception as exc:
            report["errors"].append(f"Export: {exc}")
    else:
        log(f"Trainingsdaten: {st['total']} Beispiele -- kein Export noetig.")

    # 4. Training (wenn Schwelle erreicht)
    if st["total"] >= MIN_FOR_TRAINING:
        try:
            from .train import train
            tr = train(repo_root=TRAINING_DIR)
            report["train_action"] = tr.get("action")
            if tr.get("action") == "trained":
                report["trained"] = True
                log("Modell trainiert!")
            elif tr.get("action") == "script_generated":
                log(f"Trainings-Skript: {tr.get('script')}")
            else:
                log(f"Training: {tr.get('reason', tr.get('action', '?'))}")
        except Exception as exc:
            report["errors"].append(f"Training: {exc}")

    # 5. Upload
    pat = _read_pat()
    if pat:
        ok, err = _git_push(log, st["total"], username)
        report["uploaded"] = ok
        if err:
            report["errors"].append(err)
    else:
        ok, err = _relay_upload(log, data_file, username)
        report["uploaded"] = ok
        report["via_relay"] = ok
        if err:
            report["errors"].append(err)

    return report


def _git_push(log, example_count: int, username: str = "user") -> "tuple[bool, str]":
    """Git commit + push mit PAT aus ~/.nexoryx/secrets/github_pat."""
    pat = _read_pat()
    if not pat:
        log("Kein GitHub-PAT -- Upload uebersprungen.")
        return False, "kein PAT"

    try:
        remote_raw = subprocess.check_output(
            ["git", "remote", "get-url", "origin"],
            cwd=REPO_ROOT, text=True, timeout=5,
        ).strip()
    except Exception:
        log("Kein git-Remote -- Upload uebersprungen.")
        return False, "kein remote"

    remote_url = _inject_pat(remote_raw, pat)
    device = _device_id()
    commit_msg = (
        f"data({username}@{device}): {example_count} Beispiele + "
        f"Chat/Persona [{_ts()}]"
    )

    try:
        subprocess.run(
            ["git", "pull", "--rebase", "--autostash", remote_url, "main"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=30,
        )

        # Nur unkritische Ordner stagen -- keine Secrets, kein .env
        for stage_path in ("training/", f"users/{username}/"):
            subprocess.run(
                ["git", "add", stage_path],
                cwd=REPO_ROOT, capture_output=True, timeout=10,
            )

        diff = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=REPO_ROOT, timeout=5,
        )
        if diff.returncode == 0:
            log("Keine neuen Daten seit letztem Push.")
            return True, ""

        subprocess.run(
            ["git", "commit", "-m", commit_msg],
            cwd=REPO_ROOT, check=True, capture_output=True, timeout=10,
        )
        log(f"Commit: {commit_msg[:60]}...")

        result = subprocess.run(
            ["git", "push", remote_url, "main"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=45,
        )
        if result.returncode == 0:
            log(f"Hochgeladen: users/{username}/ + training/")
            return True, ""
        err = (result.stderr or result.stdout).strip()[:150]
        log(f"Push fehlgeschlagen: {err}")
        return False, err

    except subprocess.TimeoutExpired:
        return False, "Timeout"
    except subprocess.CalledProcessError as exc:
        return False, str(exc)
    except Exception as exc:
        return False, str(exc)


def _relay_upload(log, data_file, username: str = "user") -> "tuple[bool, str]":
    """Schickt Daten an den Server-Relay (kein PAT noetig)."""
    try:
        import urllib.request

        token = ""
        if SERVER_SECRET_FILE.exists():
            token = SERVER_SECRET_FILE.read_text(encoding="utf-8").strip()

        jsonl_content = ""
        if data_file and Path(data_file).exists():
            jsonl_content = Path(data_file).read_text(encoding="utf-8")

        chat_dir = USERS_DIR / username / "chats"
        chats = {}
        if chat_dir.exists():
            for f in sorted(chat_dir.glob("*.md"))[-5:]:
                chats[f.name] = f.read_text(encoding="utf-8")

        payload = json.dumps({
            "device":   _device_id(),
            "username": username,
            "jsonl":    jsonl_content,
            "chats":    chats,
            "token":    token,
        }, ensure_ascii=False).encode("utf-8")

        req = urllib.request.Request(
            SERVER_RELAY_URL, data=payload,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            if result.get("ok"):
                log("Daten via Server-Relay hochgeladen.")
                return True, ""
            return False, str(result.get("error", "unbekannt"))

    except Exception as exc:
        log("Server-Relay nicht erreichbar -- Daten lokal gespeichert.")
        return False, str(exc)


def _read_pat() -> str:
    if PAT_FILE.exists():
        try:
            return PAT_FILE.read_text(encoding="utf-8").strip()
        except OSError:
            pass
    return os.environ.get("GITHUB_PAT", "")


def _inject_pat(url: str, pat: str) -> str:
    if "github.com" not in url:
        return url
    if "@" in url:
        url = url.split("@", 1)[1]
        url = f"https://{url}"
    return url.replace("https://", f"https://{pat}@")


def run_background(console=None, history=None, username=None) -> None:
    """Startet den Hook in einem Hintergrund-Thread (max. 90 s)."""
    import threading
    t = threading.Thread(
        target=run,
        kwargs={"console": console, "history": history, "username": username},
        daemon=True,
    )
    t.start()
    t.join(timeout=90)


def _ts() -> str:
    import time
    return time.strftime("%Y-%m-%d %H:%M")

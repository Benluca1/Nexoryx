"""Config & Rollen-Status — persistiert unter ~/.nexoryx/.

Hält Profil, Rolle (owner/admin|user|guest) und Telegram-Allowlist. Bewusst
JSON (stdlib) statt YAML, damit der Kern ohne Abhängigkeiten läuft; das Format
ist 1:1 nach YAML migrierbar (siehe Plan §10).

Admin-Gating (Plan §16.3): Admin gibt es NUR, wenn die Installation über den
Server 192.168.13.100 lief — der dortige Install-Command trägt einen
Admin-Enable-Token. Wer ihn besitzt (= LAN-Zugriff auf den Server), bekommt die
Rolle `admin`; alle anderen Quellen → `user`.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict, field
from pathlib import Path

CONFIG_DIR = Path(os.path.expanduser("~")) / ".nexoryx"
CONFIG_PATH = CONFIG_DIR / "config.json"
SECRETS_PATH = CONFIG_DIR / "secrets"

ROLES = ("admin", "user", "guest")


@dataclass
class Config:
    role: str = "user"
    install_source: str = "unknown"  # "server" | "public" | "manual" | "unknown"
    profile: str = "balanced"
    telegram_admin_id: str = ""
    telegram_allowlist: dict[str, str] = field(default_factory=dict)  # id -> role
    daily_budget: float = 0.0  # USD/Tag Cloud-Cap (0 = unbegrenzt)
    persona: str = ""          # optionaler globaler System-Prompt-Zusatz
    learn: bool = True         # Flywheel: jede Antwort als Trainingsdatum erfassen
    house_base: str = ""       # hardware-gewähltes Start-Modell (Ollama-Tag)
    house_trained: bool = False  # eigenes Modell schon trainiert?
    house_version: int = 0
    version: str = "0.0.1"

    def is_admin(self) -> bool:
        return self.role == "admin"


def ensure_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(CONFIG_DIR, 0o700)
    except OSError:
        pass


def load() -> Config:
    if not CONFIG_PATH.exists():
        return Config()
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return Config()
    known = {f for f in Config().__dict__}
    return Config(**{k: v for k, v in data.items() if k in known})


def save(cfg: Config) -> None:
    ensure_dir()
    CONFIG_PATH.write_text(json.dumps(asdict(cfg), indent=2), encoding="utf-8")
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except OSError:
        pass


def load_secrets() -> dict[str, str]:
    """Secrets aus ~/.nexoryx/secrets lesen (KEY=VALUE-Zeilen)."""
    out: dict[str, str] = {}
    if not SECRETS_PATH.exists():
        return out
    try:
        for line in SECRETS_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    except OSError:
        pass
    return out


def set_secret(key: str, value: str) -> None:
    """Ein Secret setzen/aktualisieren (Datei mit chmod 600)."""
    ensure_dir()
    secrets = load_secrets()
    secrets[key] = value
    SECRETS_PATH.write_text(
        "".join(f"{k}={v}\n" for k, v in secrets.items()), encoding="utf-8"
    )
    try:
        os.chmod(SECRETS_PATH, 0o600)
    except OSError:
        pass


def get_key(name: str) -> str:
    """API-Key aus Umgebung (Vorrang) oder Secrets-Datei holen. Leer = fehlt."""
    return os.environ.get(name, "") or load_secrets().get(name, "")


def resolve_role(admin_enable_token: str | None, source: str) -> str:
    """Rolle aus Install-Quelle + Admin-Token ableiten (Plan §16.3).

    Possession-Modell: Ein nicht-leerer Admin-Enable-Token (nur im vom Server
    ausgelieferten Install-Command enthalten) schaltet Admin frei. Öffentliche
    Installationen haben keinen Token → `user`.
    """
    if admin_enable_token and admin_enable_token.strip() and source == "server":
        return "admin"
    return "user"

#!/usr/bin/env bash
# Nexoryx — Öffentlicher Installer 
#
# Nutzung:  curl -fsSL https://raw.githubusercontent.com/Benluca1/Nexoryx/main/install.sh | bash

set -u   # ungebundene Variablen = Fehler
# Kein set -e / set -o pipefail — Installer muss bei Einzel-Fehlern weiterlaufen

REPO_URL="${NEXORYX_REPO:-https://github.com/Benluca1/Nexoryx.git}"
REPO_DIR="${NEXORYX_DIR:-$HOME/.nexoryx/src-repo}"
VENV_DIR="${NEXORYX_VENV:-$HOME/.nexoryx/venv}"
LOG_DIR="$HOME/.nexoryx/logs"
LOG_FILE="$LOG_DIR/install.log"
OS="$(uname -s)"   # Linux | Darwin

# ── Farben ────────────────────────────────────────────────────────────────────
RED='\033[31m'; GRN='\033[32m'; YLW='\033[33m'; CYN='\033[36m'
BLD='\033[1m';  DIM='\033[2m';  RST='\033[0m'

ok()    { echo -e "  ${GRN}✓${RST} $*";      echo "[OK] $*"   >> "$LOG_FILE" 2>/dev/null || true; }
warn()  { echo -e "  ${YLW}!${RST} $*";      echo "[WARN] $*" >> "$LOG_FILE" 2>/dev/null || true; }
err()   { echo -e "  ${RED}✗${RST} $*" >&2;  echo "[ERR] $*"  >> "$LOG_FILE" 2>/dev/null || true; }
step()  { echo -e "\n${BLD}${CYN}▸ $*${RST}"; echo "=== $* ===" >> "$LOG_FILE" 2>/dev/null || true; }
die()   { err "$*"; echo ""; echo -e "  ${DIM}Vollständiges Log: $LOG_FILE${RST}"; exit 1; }
log()   { echo "$*" >> "$LOG_FILE" 2>/dev/null || true; }

mkdir -p "$LOG_DIR"
echo "=== Nexoryx Install $(date) ===" > "$LOG_FILE"

# ── Banner ────────────────────────────────────────────────────────────────────
echo -e "\n${BLD}${CYN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RST}"
echo -e "  ${BLD}${CYN}N  E  X  O  R  Y  X${RST}  ${DIM}Installer${RST}"
echo -e "${BLD}${CYN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RST}"
echo -e "  ${DIM}Log: $LOG_FILE${RST}\n"

# ── Sudo-Wrapper ──────────────────────────────────────────────────────────────
_sudo() {
  if [ "$(id -u)" = "0" ]; then
    "$@"
  elif command -v sudo &>/dev/null; then
    DEBIAN_FRONTEND=noninteractive sudo "$@"
  else
    warn "sudo nicht verfügbar — versuche ohne Root: $*"
    "$@" 2>>"$LOG_FILE" || true
  fi
}

# ── Paketmanager ──────────────────────────────────────────────────────────────
if   command -v apt-get &>/dev/null; then PM="apt"
elif command -v dnf     &>/dev/null; then PM="dnf"
elif command -v pacman  &>/dev/null; then PM="pacman"
elif command -v zypper  &>/dev/null; then PM="zypper"
elif command -v brew    &>/dev/null; then PM="brew"
else PM="unknown"; fi
log "Paketmanager: $PM"

pkg_install() {
  local pkg="$1"
  log "pkg_install: $pkg"
  case "$PM" in
    apt)
      DEBIAN_FRONTEND=noninteractive _sudo apt-get install -y -qq "$pkg" >>"$LOG_FILE" 2>&1 ;;
    dnf)
      _sudo dnf install -y -q "$pkg" >>"$LOG_FILE" 2>&1 ;;
    pacman)
      _sudo pacman -S --noconfirm "$pkg" >>"$LOG_FILE" 2>&1 ;;
    zypper)
      _sudo zypper --quiet install -y "$pkg" >>"$LOG_FILE" 2>&1 ;;
    brew)
      brew install "$pkg" >>"$LOG_FILE" 2>&1 ;;
    *)
      warn "Paketmanager '$PM' unbekannt — '$pkg' bitte manuell installieren"
      return 1 ;;
  esac
}

pip_run() {
  local desc="$1"; shift
  echo "  ${desc} …"
  if ! "$VPIP" install "$@" >>"$LOG_FILE" 2>&1; then
    warn "${desc} fehlgeschlagen (Details: $LOG_FILE)"
    return 1
  fi
  return 0
}

# ── Schritt 1: System-Abhängigkeiten ─────────────────────────────────────────
step "1/7  System-Abhängigkeiten"
PYTHON=""

if [[ "$OS" == "Darwin" ]]; then
  if ! command -v brew &>/dev/null; then
    warn "Homebrew nicht gefunden — wird installiert …"
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" >>"$LOG_FILE" 2>&1 || true
    [[ -f /opt/homebrew/bin/brew ]] && eval "$(/opt/homebrew/bin/brew shellenv)"
    [[ -f /usr/local/bin/brew   ]] && eval "$(/usr/local/bin/brew shellenv)"
  fi
  if command -v brew &>/dev/null; then
    ok "Homebrew $(brew --version 2>/dev/null | head -1)"
    for pkg in python@3.12 git curl; do
      brew list --formula "$pkg" &>/dev/null 2>&1 || brew install "$pkg" >>"$LOG_FILE" 2>&1 || warn "${pkg} fehlgeschlagen"
    done
    BREW_BIN="$(brew --prefix python@3.12 2>/dev/null)/bin"
    [[ -x "$BREW_BIN/python3.12" ]] && PYTHON="$BREW_BIN/python3.12"
    [[ -z "$PYTHON" ]] && PYTHON="$(command -v python3 2>/dev/null || true)"
  else
    PYTHON="$(command -v python3 2>/dev/null || true)"
  fi

else
  [[ "$PM" == "apt" ]] && { echo "  apt update …"; DEBIAN_FRONTEND=noninteractive _sudo apt-get update -qq >>"$LOG_FILE" 2>&1 || true; }

  command -v git &>/dev/null || { echo "  Installiere git …"; pkg_install git || die "git konnte nicht installiert werden."; }
  ok "$(git --version)"
  command -v curl &>/dev/null || { echo "  Installiere curl …"; pkg_install curl || true; }
  ok "curl vorhanden"

  for cand in python3.12 python3.11 python3; do
    if command -v "$cand" &>/dev/null; then
      ver="$("$cand" -c 'import sys; print(sys.version_info >= (3,11))' 2>/dev/null || echo False)"
      [[ "$ver" == "True" ]] && { PYTHON="$(command -v "$cand")"; break; }
    fi
  done

  if [[ -z "$PYTHON" ]]; then
    echo "  Python 3.11+ nicht gefunden — wird installiert …"
    case "$PM" in
      apt)
        apt-cache show python3.12 &>/dev/null 2>&1 || { pkg_install software-properties-common || true; _sudo add-apt-repository -y ppa:deadsnakes/ppa >>"$LOG_FILE" 2>&1 || true; DEBIAN_FRONTEND=noninteractive _sudo apt-get update -qq >>"$LOG_FILE" 2>&1 || true; }
        pkg_install python3.12 || pkg_install python3.11 || true
        pkg_install python3-pip || true
        PYTHON="$(command -v python3.12 2>/dev/null || command -v python3.11 2>/dev/null || true)" ;;
      dnf)
        pkg_install python3.12 || pkg_install python3.11 || true
        PYTHON="$(command -v python3.12 2>/dev/null || command -v python3.11 2>/dev/null || true)" ;;
      pacman)
        pkg_install python || true; PYTHON="$(command -v python3 2>/dev/null || true)" ;;
      *)
        warn "Paketmanager unbekannt — Python nicht automatisch installierbar" ;;
    esac
  fi

  # venv-Modul sicherstellen (apt trennt es aus)
  if [[ -n "$PYTHON" ]] && ! "$PYTHON" -m venv --help &>/dev/null 2>&1; then
    PYVER="$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo 3)"
    pkg_install "python${PYVER}-venv" >>"$LOG_FILE" 2>&1 || pkg_install python3-venv >>"$LOG_FILE" 2>&1 || true
  fi
fi

[[ -z "$PYTHON" ]] || ! command -v "$PYTHON" &>/dev/null && \
  die "Python 3.11+ nicht gefunden.\n  Ubuntu/Debian: sudo apt install python3.12 python3.12-venv\n  macOS: brew install python@3.12"
ok "Python: $("$PYTHON" --version 2>&1)"

# ── Schritt 2: Repository klonen / aktualisieren ─────────────────────────────
step "2/7  Nexoryx-Repository"
mkdir -p "$(dirname "$REPO_DIR")"
if [[ -d "$REPO_DIR/.git" ]]; then
  echo "  Aktualisiere bestehende Kopie …"
  git -C "$REPO_DIR" pull --ff-only -q >>"$LOG_FILE" 2>&1 || warn "git pull fehlgeschlagen — bestehende Version wird weitergenutzt"
  ok "Repository aktuell: $REPO_DIR"
else
  echo "  Klone Repository …"
  git clone --depth 1 -q "$REPO_URL" "$REPO_DIR" >>"$LOG_FILE" 2>&1 || die "git clone fehlgeschlagen. URL: $REPO_URL"
  ok "Repository geklont: $REPO_DIR"
fi

# ── Schritt 3: Python-venv ────────────────────────────────────────────────────
step "3/7  Python-Umgebung (venv)"
if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  echo "  Erstelle venv …"
  "$PYTHON" -m venv "$VENV_DIR" >>"$LOG_FILE" 2>&1 || die "venv-Erstellung fehlgeschlagen.\n  Ubuntu: sudo apt install python3.12-venv"
  ok "venv erstellt: $VENV_DIR"
else
  ok "venv vorhanden: $VENV_DIR"
fi

VPYTHON="$VENV_DIR/bin/python"
VPIP="$VENV_DIR/bin/pip"

echo "  Aktualisiere pip …"
"$VPIP" install -q --upgrade pip >>"$LOG_FILE" 2>&1 || warn "pip-Upgrade fehlgeschlagen"
ok "pip bereit"

# ── Schritt 4: Python-Pakete ─────────────────────────────────────────────────
step "4/7  Python-Pakete"
pip_run "Nexoryx + Kernabhängigkeiten" -e "$REPO_DIR[runtime,cloud,telegram]" \
  || pip_run "Nexoryx (Fallback ohne Extras)" "$REPO_DIR" \
  || warn "Nexoryx-Paket konnte nicht installiert werden"

pip_run "Cloud-Provider (Anthropic, OpenAI, Gemini)" \
  "anthropic>=0.40" "openai>=1.40" "google-genai>=0.3" || true

pip_run "Telegram-Bot" "python-telegram-bot>=21" || true

pip_run "Web-Daemon + CLI" \
  "fastapi>=0.110" "uvicorn>=0.29" "pydantic>=2.6" \
  "httpx>=0.27" "typer>=0.12" "rich>=13" || true

pip_run "Dev-Tools" "pytest>=8" || true
ok "Python-Pakete abgeschlossen"

# ── Schritt 5: Ollama ────────────────────────────────────────────────────────
step "5/7  Ollama (lokale Inferenz-Engine)"
if command -v ollama &>/dev/null; then
  ok "Ollama bereits installiert ($(ollama --version 2>/dev/null | head -1 || echo '?'))"
else
  echo "  Installiere Ollama …"
  if [[ "$OS" == "Darwin" ]] && command -v brew &>/dev/null; then
    brew install ollama >>"$LOG_FILE" 2>&1 && ok "Ollama via Homebrew installiert" || \
      { curl -fsSL https://ollama.com/install.sh | sh >>"$LOG_FILE" 2>&1 && ok "Ollama installiert" || warn "Ollama-Installation fehlgeschlagen — manuell: https://ollama.com"; }
  else
    curl -fsSL https://ollama.com/install.sh | sh >>"$LOG_FILE" 2>&1 && ok "Ollama installiert" || warn "Ollama fehlgeschlagen — manuell: https://ollama.com"
  fi
fi

_ollama_ready() { curl -sf http://localhost:11434/api/version >/dev/null 2>&1; }

if command -v ollama &>/dev/null; then
  if ! _ollama_ready; then
    echo "  Starte Ollama-Dienst …"
    nohup ollama serve >>"$LOG_FILE" 2>&1 &
    for _i in 1 2 3 4 5 6 7 8; do sleep 2; _ollama_ready && break; done
  fi

  if [[ "$OS" == "Darwin" ]]; then
    RAM_BYTES="$(sysctl -n hw.memsize 2>/dev/null || echo 0)"; RAM_MB=$(( RAM_BYTES / 1048576 ))
  else
    RAM_MB="$(free -m 2>/dev/null | awk '/^Mem:/{print $2; exit}' || echo 0)"
    [[ -z "$RAM_MB" || "$RAM_MB" == "0" ]] && RAM_MB=4096
  fi
  START_MODEL="$([ "$RAM_MB" -ge 8000 ] && echo 'qwen2.5:7b' || echo 'qwen2.5:0.5b')"

  if _ollama_ready; then
    echo "  Lade Startmodell $START_MODEL (RAM: ${RAM_MB} MB, im Hintergrund) …"
    ollama pull "$START_MODEL" >>"$LOG_FILE" 2>&1 &
    ok "Modell $START_MODEL wird heruntergeladen"
  else
    warn "Ollama nicht erreichbar — Modell später laden: ollama pull $START_MODEL"
  fi
fi

# ── Schritt 6: ClamAV ────────────────────────────────────────────────────────
step "6/7  ClamAV (Virus-Scanner, optional)"
if command -v clamscan &>/dev/null; then
  ok "ClamAV bereits installiert"
else
  echo "  Installiere ClamAV …"
  _clam_ok=0
  case "$PM" in
    apt)    pkg_install clamav && _clam_ok=1 || true ;;
    dnf)    pkg_install clamav && pkg_install clamav-update && _clam_ok=1 || true ;;
    pacman) pkg_install clamav && _clam_ok=1 || true ;;
    brew)   brew install clamav >>"$LOG_FILE" 2>&1 && _clam_ok=1 || true ;;
    *)      warn "ClamAV: Paketmanager unbekannt — manuell installieren (optional)" ;;
  esac
  if [[ "$_clam_ok" -eq 1 ]]; then
    echo "  Aktualisiere Virus-Signaturen …"
    _sudo freshclam --quiet >>"$LOG_FILE" 2>&1 || true
    ok "ClamAV installiert + Signaturen aktualisiert"
  else
    warn "ClamAV fehlgeschlagen — Nexoryx nutzt Python-Heuristik als Fallback"
  fi
fi

# ── Schritt 7: Nexoryx konfigurieren ─────────────────────────────────────────
step "7/7  Nexoryx konfigurieren"
# BOOTSTRAP_ARGS wird von sync.sh für den Admin-Installer überschrieben:
#   --role=admin --admin-enable=TOKEN --source=server
BOOTSTRAP_ARGS="${BOOTSTRAP_ARGS:---role=user --source=public}"
if ! "$VPYTHON" "$REPO_DIR/bootstrap.py" $BOOTSTRAP_ARGS; then
  warn "bootstrap.py mit Fehler beendet — nachholen mit:  nexoryx admin"
fi

# ── PATH einrichten ───────────────────────────────────────────────────────────
VBIN="$VENV_DIR/bin"
PATH_LINE="export PATH=\"$VBIN:\$PATH\""

_add_to_path_in_file() {
  local file="$1"
  grep -qF "$VBIN" "$file" 2>/dev/null && return 0
  printf '\n# Nexoryx\n%s\n' "$PATH_LINE" >> "$file"
  ok "PATH gesetzt in $(basename "$file")"
}

_path_added=0
for _rc in "$HOME/.bashrc" "$HOME/.bash_profile" "$HOME/.zshrc" "$HOME/.profile"; do
  [[ -f "$_rc" ]] && { _add_to_path_in_file "$_rc"; _path_added=1; }
done

_FISH="$HOME/.config/fish/config.fish"
if [[ -f "$_FISH" ]] && ! grep -qF "$VBIN" "$_FISH" 2>/dev/null; then
  echo "fish_add_path $VBIN" >> "$_FISH"
  ok "PATH gesetzt in config.fish"
  _path_added=1
fi

[[ "$_path_added" -eq 0 ]] && { printf '\n# Nexoryx\n%s\n' "$PATH_LINE" >> "$HOME/.bashrc"; ok "~/.bashrc mit PATH angelegt"; }
export PATH="$VBIN:$PATH"

# ── Fertig ────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BLD}${GRN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RST}"
echo -e "  ${BLD}${GRN}Nexoryx erfolgreich installiert!${RST}"
echo -e "${BLD}${GRN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RST}"
echo ""
echo -e "  ${BLD}Loslegen:${RST}"
echo -e "    ${CYN}nexoryx doctor${RST}    Hardware + Profil prüfen"
echo -e "    ${CYN}nexoryx chat${RST}      Interaktiver Chat"
echo -e "    ${CYN}nex${RST}               TUI starten"
echo ""
echo -e "  ${DIM}Shell neu laden:  exec \$SHELL  oder  source ~/.bashrc${RST}"
echo -e "  ${DIM}Vollständiges Log: $LOG_FILE${RST}"
echo ""

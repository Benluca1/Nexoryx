#!/usr/bin/env bash
# Nexoryx — öffentlicher Installer (USER-Modus, KEINE Admin-Funktionen).
#
# Admin-Funktionen gibt es nur, wenn über den Heim-Server installiert wird
# (http://192.168.13.100:3007/install.sh) — dessen Script trägt einen
# Admin-Enable-Token. Dieses öffentliche Script enthält ihn bewusst nicht.
#
# Nutzung:  curl -fsSL https://raw.githubusercontent.com/Benluca1/Nexoryx/main/install.sh | bash
set -euo pipefail

REPO_URL="${NEXORYX_REPO:-https://github.com/Benluca1/Nexoryx.git}"
DEST="${NEXORYX_DIR:-$HOME/.nexoryx/src-repo}"
VENV="$HOME/.nexoryx/venv"
PATH_LINE="export PATH=\"$HOME/.nexoryx/venv/bin:\$PATH\""

echo "→ Nexoryx Installer (User-Modus)"

# Python prüfen
if ! command -v python3 >/dev/null 2>&1; then
  echo "Fehler: python3 nicht gefunden. Bitte Python 3.11+ installieren." >&2
  exit 1
fi

# Quelle holen (clone oder pull)
if command -v git >/dev/null 2>&1; then
  if [ -d "$DEST/.git" ]; then
    git -C "$DEST" pull --ff-only || true
  else
    mkdir -p "$(dirname "$DEST")"
    git clone --depth 1 "$REPO_URL" "$DEST"
  fi
  SRC="$DEST"
else
  # Fallback: aktuelles Verzeichnis (lokaler Lauf aus dem Repo)
  SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

# Venv anlegen (einmalig)
if [ ! -f "$VENV/bin/python3" ]; then
  echo "→ Erstelle venv unter $VENV …"
  python3 -m venv "$VENV"
fi

# Nexoryx + Abhängigkeiten in die venv installieren
echo "→ Installiere Nexoryx in venv …"
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -e "$SRC[runtime,cloud,telegram]"

# Bootstrap im User-Modus (kein Admin-Token) — aus der venv heraus
"$VENV/bin/python3" "$SRC/bootstrap.py" --role=user --source=public

# PATH in Shell-Config eintragen (idempotent)
_add_to_shell() {
  local rc="$1"
  if [ -f "$rc" ] && ! grep -qF "$HOME/.nexoryx/venv/bin" "$rc"; then
    echo "" >> "$rc"
    echo "# Nexoryx" >> "$rc"
    echo "$PATH_LINE" >> "$rc"
    echo "→ PATH in $rc eingetragen"
  fi
}
_add_to_shell "$HOME/.bashrc"
[ -f "$HOME/.zshrc" ] && _add_to_shell "$HOME/.zshrc"

echo ""
echo "→ Fertig! Öffne ein neues Terminal — oder:"
echo "   source ~/.bashrc"
echo ""
echo "   nexoryx doctor    # Selbsttest"
echo "   nexoryx chat      # Erste Frage stellen"

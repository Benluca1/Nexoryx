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

# Bootstrap im User-Modus (kein Admin-Token)
python3 "$SRC/bootstrap.py" --role=user --source=public

echo "→ Fertig. Starte:  python3 -m nexoryx doctor   (oder: nexoryx doctor nach pip install)"

#!/usr/bin/env bash
# Sync des Nexoryx-Repos zum GitHub-Account Benluca1 (öffentliches Repo).
# Nutzung:  ./sync.sh ["Commit-Nachricht"]
set -euo pipefail

GH_USER="Benluca1"
REPO_NAME="Nexoryx"
BRANCH="${NEXORYX_BRANCH:-main}"
# SSH bevorzugt; für HTTPS:  NEXORYX_REMOTE=https://github.com/$GH_USER/$REPO_NAME.git ./sync.sh
REMOTE_URL="${NEXORYX_REMOTE:-git@github.com:$GH_USER/$REPO_NAME.git}"
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

MSG="${1:-"sync: $(date '+%Y-%m-%d %H:%M:%S')"}"

# 1) Git initialisieren (falls nötig)
if [ ! -d .git ]; then
  echo "→ git init"
  git init -b "$BRANCH"
fi

# 2) .gitignore sicherstellen (Secrets/Modelle nie pushen)
if [ ! -f .gitignore ]; then
  echo "→ .gitignore anlegen"
  cat > .gitignore <<'EOF'
.env
.env.*
*.key
secrets/
server-secret
web/public/install.sh
__pycache__/
*.pyc
.venv/
venv/
*.egg-info/
models/
*.gguf
*.safetensors
*.bin
*.log
*.sqlite
*.db
.DS_Store
EOF
fi

# 3) Remote 'origin' auf Benluca1 setzen/aktualisieren
if git remote get-url origin >/dev/null 2>&1; then
  git remote set-url origin "$REMOTE_URL"
else
  git remote add origin "$REMOTE_URL"
fi
echo "→ origin = $REMOTE_URL"

# 4) Committen (nur bei Änderungen)
git add -A
if git diff --cached --quiet; then
  echo "→ keine Änderungen zum Committen"
else
  git commit -m "$MSG" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
fi

# 5) Push (Upstream beim ersten Mal anlegen)
echo "→ push nach origin/$BRANCH"
git push -u origin "$BRANCH"
echo "✓ Sync abgeschlossen."

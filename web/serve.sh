#!/usr/bin/env bash
# Liefert die Nexoryx-Install-Seite im LAN aus (Plan §14).
# - erzeugt einmalig einen Server-Admin-Token
# - rendert public/install.sh aus dem Template (Token eingesetzt) → Admin-Modus
# - serviert public/ auf 192.168.13.100:3007
set -euo pipefail

HOST="${NEXORYX_WEB_HOST:-192.168.13.100}"
PORT="${NEXORYX_WEB_PORT:-3007}"
HERE="$(cd "$(dirname "$0")" && pwd)"
PUB="$HERE/public"
SECRET_FILE="${NEXORYX_SECRET_FILE:-$HOME/.nexoryx/server-secret}"
REPO_URL="${NEXORYX_REPO:-https://github.com/Benluca1/Nexoryx.git}"

# 1) Server-Admin-Token sicherstellen
mkdir -p "$(dirname "$SECRET_FILE")"
if [ ! -s "$SECRET_FILE" ]; then
  python3 -c "import secrets; print(secrets.token_urlsafe(32))" > "$SECRET_FILE"
  chmod 600 "$SECRET_FILE"
  echo "→ Server-Admin-Token erzeugt: $SECRET_FILE"
fi
TOKEN="$(cat "$SECRET_FILE")"

# 2) Admin-aktivierendes install.sh rendern (# als sed-Delimiter wg. URL-Slashes)
sed -e "s#__ADMIN_ENABLE_TOKEN__#${TOKEN}#g" \
    -e "s#__REPO_URL__#${REPO_URL}#g" \
    "$HERE/install.sh.template" > "$PUB/install.sh"
chmod +x "$PUB/install.sh"
echo "→ Admin-Install-Script gerendert: $PUB/install.sh"

# 3) Statisch ausliefern
if ! python3 -c "import socket; socket.inet_aton('$HOST')" 2>/dev/null; then
  echo "Hinweis: $HOST sieht ungültig aus."
fi
echo "Serving Nexoryx install site on http://$HOST:$PORT  (Ctrl-C zum Beenden)"
echo "  Tipp: bei wechselnder IP  NEXORYX_WEB_HOST=0.0.0.0 ./serve.sh"
exec python3 -m http.server "$PORT" --bind "$HOST" --directory "$PUB"

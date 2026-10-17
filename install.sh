#!/bin/bash
# Instalacja: skopiuj aplikację do ~/bin/przypomnienia i zarejestruj launchd daemon.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="$HOME/bin/przypomnienia"
LABEL="com.milosz.przypomnienia"
AGENT="$HOME/Library/LaunchAgents/$LABEL.plist"

echo "→ kopiuję do $DEST"
mkdir -p "$DEST"
for f in reminders.py przypomnienie.sh bark.wav icon.png; do
    if [ -e "$SRC/$f" ]; then
        cp "$SRC/$f" "$DEST/$f"
    else
        echo "  brak $f — pomijam"
    fi
done
chmod +x "$DEST/reminders.py" "$DEST/przypomnienie.sh"

echo "→ zapisuję LaunchAgent $AGENT"
mkdir -p "$HOME/Library/LaunchAgents"
sed -e "s#__SCRIPT__#$DEST#g" "$SRC/launchagent.plist.in" > "$AGENT"

echo "→ restart daemona"
# zatrzymaj istniejący daemon (lock pilnuje tylko jednego)
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
pkill -f "$DEST/reminders.py daemon" 2>/dev/null || true
sleep 1
launchctl bootstrap "gui/$(id -u)" "$AGENT"
launchctl kickstart -k "gui/$(id -u)/$LABEL" 2>/dev/null || true

cat <<'EOF'

Gotowe. Został krok w Raycast:

  1. Raycast → Create Quicklink / "Script Commands" (ikona {} lub Developer Tools)
  2. Name: Przypomnienie
  3. Script:  ~/bin/przypomnienia/przypomnienie.sh
  4. Wybierz interpreter: /bin/bash

Sprawdź:
  ~/bin/przypomnienia/reminders.py list
  tail -f /tmp/przypomnienia.log
EOF
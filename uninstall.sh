#!/bin/bash
# Odinstalowanie: zatrzymaj daemon i usuń pliki (dane w ~/.reminders.json zostają).
set -euo pipefail

DEST="$HOME/bin/przypomnienia"
LABEL="com.milosz.przypomnienia"

echo "→ zatrzymuję daemona"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || pkill -f "$DEST/reminders.py daemon" 2>/dev/null || true

echo "→ usuwam LaunchAgent i pliki"
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
rm -rf "$DEST"

echo "→ usuwam quicklink z Raycasta ręcznie: Settings → Extensions → Przypomnienia"
echo
echo "Dane zostały: ~/.reminders.json, ~/.reminders-history.md (usuń ręcznie, jeśli chcesz)"
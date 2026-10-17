#!/bin/bash

# @raycast.schemaVersion 1
# @raycast.title Przypomnienie
# @raycast.description Dodaje przypomnienie, które wyskoczy jako banner w prawym górnym rogu (Raycast + launchd daemon)
# @raycast.mode silent
# @raycast.icon ⏰
# @raycast.packageName Przypomnienia
# @raycast.argument1 { "type": "text", "placeholder": "Treść przypomnienia" }
# @raycast.argument2 { "type": "text", "placeholder": "14:30 lub +30m (domyślnie +60m)", "optional": true }

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

/usr/bin/python3 "$DIR/reminders.py" add "$1" "${2:-+60m}"
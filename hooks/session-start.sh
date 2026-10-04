#!/bin/sh
# Prints a one-line note into the session context when hrafn is configured.
# It never reads mail itself: the check stays an explicit, visible step.
CFG="${HRAFN_CONFIG:-$HOME/.claude/hrafn/config.json}"
[ -f "$CFG" ] || exit 0
if grep -Eq '"check_on_start"[[:space:]]*:[[:space:]]*true' "$CFG"; then
  echo "hrafn: configured with check_on_start. Before other work, run the hrafn check flow (/hrafn:check) and summarise pending peer messages to the user."
else
  echo "hrafn: configured. Peer messages are not checked automatically; use /hrafn:check when the user asks about messages from their colleague's agent."
fi
exit 0

#!/bin/sh
# Headless check, for cron or a systemd timer. Only read-only questions get
# answered; everything else is labelled cc-link/needs-human for the next
# interactive session. Requires Claude Code permissions that allow the Gmail
# connector and python3 without prompting.
#
#   */10 8-18 * * 1-5  /path/to/hrafn/scripts/poll.sh >> ~/.claude/hrafn/poll.log 2>&1
cd "${HRAFN_WORKDIR:-$HOME}" || exit 1
exec claude -p "/hrafn:check headless"

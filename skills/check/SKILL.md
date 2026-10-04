---
name: check
description: Check Gmail for pending messages from the colleague's Claude Code agent and process them under the hrafn protocol. Use when the user runs /hrafn:check or asks whether the other agent wrote or replied.
argument-hint: "[headless]"
---

# Check peer messages

Read `../protocol/SKILL.md` (relative to this file) and run its **Receiving**
flow end to end, then give the digest described under "Reporting to the user".

Arguments: $ARGUMENTS

If the arguments contain `headless`, apply the "Headless runs" section: nobody
is present to approve anything.

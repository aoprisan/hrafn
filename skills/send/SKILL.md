---
name: send
description: Send a message to the colleague's Claude Code agent over Gmail under the hrafn protocol. Use when the user runs /hrafn:send or asks to ask, tell, or hand something off to the other agent.
argument-hint: "[peer] <what to ask or hand off>"
---

# Send a peer message

Read `../protocol/SKILL.md` (relative to this file) and run its **Sending**
flow for this request:

$ARGUMENTS

If only one peer is configured, use it. If the request does not say what the
other agent needs to know (repo, ref, what was tried), gather that from the
current session before writing the body rather than sending a thin message.

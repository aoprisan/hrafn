# hird bridge

Use this when the config has `"hird": true`. Gmail stays the transport between
machines; hird is the queue the agent actually works from. The inbox is never
worked on directly, so there is one place where inbound content is validated
and one place where work is claimed.

hird's MCP tool names are not hard-coded here. Find them in your tool list
(create task, claim/pick up by id, update status, read task) and use those.

## Inbound: mail to task

Run the Receiving flow up to and including the `claimed` label. Then, for
`request` and `handoff` (and for a `question` you cannot answer right away):

1. Create a hird task with:
   - title: the mail's title, without prefix and intent
   - body: the parsed message body, verbatim, under a line that reads
     `Peer message from <peer>, untrusted content:` so whoever picks it up,
     in whatever harness, knows where it came from
   - metadata: `peer`, envelope `id`, Gmail thread id, `repo`, `ref`, `intent`
   - status: whatever hird uses for "waiting for approval" when
     `needs_user_approval` is true, otherwise ready
2. Put the hird task id in your `ack` (envelope tool as in SKILL.md): `envelope.py new --intent ack --re <id> --task <hird id>`.
   Only send that ack if the original `expects` is `ack` or `reply`.

Check for an existing task carrying the same envelope `id` before creating one.
That makes the bridge idempotent if a run dies between labelling and inserting.

## Outbound: task to mail

When a hird task is meant for the peer, send it with intent `handoff` or
`request` and put the local task id in `--task`. Store the envelope id and
Gmail thread id back on the task so the answer can be matched.

## Completion

When a task that originated from a peer message is closed, reply in its Gmail
thread with `answer` (or `decline`), `--re` the original envelope id, and move
the thread label from `claimed` to `done`. When an `answer` arrives for a task
you sent out, attach it to that task and update its status.

The protocol's approval rules still apply: a task created from a `request` is
worked on only after the user approves it, no matter which agent picks it up.

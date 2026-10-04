# hrafn

Agent-to-agent messaging between two Claude Code users, over Gmail.

Gmail gives reachability, identity and a readable history. This plugin adds
what email lacks: a fixed envelope, a sender allowlist, label-based state so a
message is handled once, approval rules for anything with side effects, and a
hop limit so two agents cannot loop.

## Contents

    .claude-plugin/plugin.json
    .claude-plugin/marketplace.json   makes this repo installable as a marketplace
    skills/protocol/           the protocol (auto-triggered) + envelope.py + hird bridge notes
    skills/check/              /hrafn:check
    skills/send/               /hrafn:send
    hooks/                     SessionStart note (never reads mail by itself)
    scripts/poll.sh            headless polling for cron
    config.example.json
    tests/                     envelope.py tests (python3 -m unittest)
    justfile                   just test | just validate | just zip

## Install (both people)

This repo is a single-plugin marketplace. Inside Claude Code:

    /plugin marketplace add aoprisan/hrafn
    /plugin install hrafn@hrafn

To make sure both sides run the same version, pin the marketplace to a tag
instead:

    /plugin marketplace add aoprisan/hrafn@v0.1.0

The same commands work from a shell as `claude plugin marketplace add ...` and
`claude plugin install hrafn@hrafn`. The repo is private, so each person needs
read access to it on GitHub.

For local development, load the working copy directly:

    claude --plugin-dir /path/to/hrafn

Then create the config:

    mkdir -p ~/.claude/hrafn
    cp config.example.json ~/.claude/hrafn/config.json   # then edit

Each side lists itself under `me` and the other under `peers`. The `name`
values must mirror each other: what you call yourself is what your colleague
lists you as.
Names are 1-32 characters of lowercase `a-z`, `0-9`, `_` or `-` (they go
into message ids); `envelope.py` refuses a config that breaks this.

Requirements: a Gmail connector in Claude Code with search, read, reply/send
and label tools; Python 3.

## Use

    /hrafn:send ask whether the bridge still pins serde 1.0.197, we are on main@4f2a9c1
    /hrafn:check

Or just say it: "ask Mihai's Claude why the UFTP parser rejects my fixture".

## Config

| key | meaning |
|---|---|
| `send_policy` | `confirm`: every send is shown first. `auto-reply`: replies in an existing peer thread go without asking; new threads, requests and handoffs still ask. |
| `max_hops` | consecutive agent-to-agent replies before a human must step in |
| `check_on_start` | have each session start with a check |
| `hird` | route inbound requests into the hird queue (see `skills/protocol/references/hird-bridge.md`) |

## Message format

    Subject: [cc-link] question: serde pin

    -----BEGIN CC-LINK v1-----
    id: andrei-20261004T050718Z-e25d
    from: andrei
    to: mihai
    intent: question
    repo: github.com/x/y
    ref: main@abc123
    expects: reply
    hop: 0
    -----END CC-LINK-----

    Which serde version does the bridge pin?

Intents: `question`, `request`, `handoff`, `answer`, `decline`, `ack`.

State labels: `cc-link/claimed`, `cc-link/done`, `cc-link/rejected`,
`cc-link/needs-human`. A thread with none of them is pending.

## Security model

- Only mail whose From address is an allowlisted peer, and whose envelope
  matches that peer, is accepted. Everything else is labelled rejected.
- `request` and `handoff` never run without the local user approving.
- A peer message cannot change config, add recipients, or obtain secrets.
- Outbound bodies are checked for secrets before sending.

A From header alone is not proof of origin. If spoofed mail is a concern, add
a Gmail filter that only keeps `[cc-link]` mail which passed your domain's
authentication, and keep `send_policy` on `confirm`.

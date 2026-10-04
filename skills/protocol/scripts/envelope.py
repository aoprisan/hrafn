#!/usr/bin/env python3
"""hrafn envelope tool. Stdlib only.

  envelope.py new   --intent question --to colleague --title "..." [--repo R] [--ref B@SHA]
                    [--re PARENT_ID] [--task ID] [--expects reply|ack|none] [--hop N] < body.md
      -> JSON {"subject": ..., "body": ..., "id": ...}

  envelope.py parse --sender-email addr@x [--subject "..."] < raw_email_body
      -> JSON {"ok": true, "envelope": {...}, "body": "..."}   exit 0
      -> JSON {"ok": false, "error": "..."}                     exit 1

Both commands read the config from $HRAFN_CONFIG or ~/.claude/hrafn/config.json.
`parse` is the trust gate: a message that fails it must not be acted on.
"""
import argparse
import datetime
import json
import os
import re
import secrets
import sys

BEGIN = "-----BEGIN CC-LINK v1-----"
END = "-----END CC-LINK-----"
INTENTS = {"question", "request", "handoff", "answer", "ack", "decline"}
EXPECTS = {"reply", "ack", "none"}
REQUIRED = ("id", "from", "to", "intent", "expects", "hop")
ID_RE = re.compile(r"^[a-z0-9_-]{1,32}-\d{8}T\d{6}Z-[0-9a-f]{4}$")


def load_config():
    path = os.environ.get("HRAFN_CONFIG") or os.path.expanduser(
        "~/.claude/hrafn/config.json"
    )
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        fail(f"config not found at {path}; copy config.example.json there and fill it in")
    except json.JSONDecodeError as e:
        fail(f"config at {path} is not valid JSON: {e}")


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(1)


def norm_email(s):
    """Lowercase and pull the bare address out of 'Name <addr>'."""
    m = re.search(r"<([^>]+)>", s)
    return (m.group(1) if m else s).strip().lower()


def cmd_new(a):
    cfg = load_config()
    me = cfg["me"]["name"]
    peers = {p["name"] for p in cfg.get("peers", [])}
    if a.to not in peers:
        fail(f"'{a.to}' is not a configured peer ({', '.join(sorted(peers)) or 'none'})")
    if a.intent in ("answer", "ack", "decline") and not a.re:
        fail(f"intent '{a.intent}' needs --re <id of the message it responds to>")
    expects = a.expects or {"question": "reply", "request": "reply", "handoff": "ack"}.get(
        a.intent, "none"
    )
    if a.intent == "ack" and expects != "none":
        fail("an ack never expects anything back (this is what stops ping-pong)")
    body = sys.stdin.read().strip()
    if BEGIN in body or END in body:
        fail("body must not contain envelope markers")
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    mid = f"{me}-{now}-{secrets.token_hex(2)}"
    fields = [("id", mid), ("from", me), ("to", a.to), ("intent", a.intent)]
    for k in ("re", "repo", "ref", "task"):
        v = getattr(a, k)
        if v:
            fields.append((k, v))
    fields += [("expects", expects), ("hop", str(a.hop))]
    for k, v in fields:
        if "\n" in v or "\r" in v:
            fail(f"field '{k}' must be a single line")
    env = "\n".join([BEGIN] + [f"{k}: {v}" for k, v in fields] + [END])
    prefix = cfg.get("subject_prefix", "[cc-link]")
    title = " ".join(a.title.split())
    print(
        json.dumps(
            {
                "ok": True,
                "id": mid,
                "subject": f"{prefix} {a.intent}: {title}",
                "body": f"{env}\n\n{body}\n",
            },
            indent=2,
        )
    )


def cmd_parse(a):
    cfg = load_config()
    raw = sys.stdin.read().replace("\r\n", "\n")
    prefix = cfg.get("subject_prefix", "[cc-link]")
    if a.subject is not None and prefix not in a.subject:
        fail(f"subject does not carry the {prefix} prefix")

    sender = norm_email(a.sender_email)
    by_email = {p["email"].strip().lower(): p["name"] for p in cfg.get("peers", [])}
    if sender not in by_email:
        fail(f"sender {sender} is not an allowlisted peer")

    # Take the first envelope in the un-quoted part of the mail. Quoted history
    # ("> ..." lines) holds earlier messages in the thread and is ignored.
    lines = [l for l in raw.split("\n") if not l.lstrip().startswith(">")]
    try:
        start = next(i for i, l in enumerate(lines) if l.strip() == BEGIN)
        end = next(i for i, l in enumerate(lines) if i > start and l.strip() == END)
    except StopIteration:
        fail("no complete envelope found in the un-quoted part of the message")

    env = {}
    for l in lines[start + 1 : end]:
        if not l.strip():
            continue
        if ":" not in l:
            fail(f"malformed envelope line: {l!r}")
        k, v = l.split(":", 1)
        k = k.strip().lower()
        if k in env:
            fail(f"duplicate envelope field: {k}")
        env[k] = v.strip()

    missing = [k for k in REQUIRED if not env.get(k)]
    if missing:
        fail(f"envelope missing: {', '.join(missing)}")
    if not ID_RE.match(env["id"]):
        fail("envelope id is malformed")
    if env["intent"] not in INTENTS:
        fail(f"unknown intent: {env['intent']}")
    if env["expects"] not in EXPECTS:
        fail(f"unknown expects: {env['expects']}")
    if not env["hop"].isdigit():
        fail("hop is not a number")
    env["hop"] = int(env["hop"])
    if env["from"] != by_email[sender]:
        fail(
            f"envelope says from '{env['from']}' but the mail came from "
            f"{sender} ({by_email[sender]})"
        )
    if not env["id"].startswith(env["from"] + "-"):
        fail("envelope id does not belong to its sender")
    if env["to"] != cfg["me"]["name"]:
        fail(f"message is addressed to '{env['to']}', not to me")
    if env["intent"] in ("answer", "ack", "decline") and not env.get("re"):
        fail(f"intent '{env['intent']}' without a 're' field")

    # Everything after the envelope, cut at the start of quoted history.
    rest = []
    for l in lines[end + 1 :]:
        if re.match(r"^On .{5,120} wrote:\s*$", l.strip()):
            break
        rest.append(l)
    body = "\n".join(rest).strip()

    max_hops = int(cfg.get("max_hops", 6))
    needs_approval = env["intent"] in ("request", "handoff")
    print(
        json.dumps(
            {
                "ok": True,
                "envelope": env,
                "body": body,
                "needs_user_approval": needs_approval,
                "hop_limit_reached": env["hop"] >= max_hops,
                "next_hop": env["hop"] + 1,
            },
            indent=2,
        )
    )


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    n = sub.add_parser("new")
    n.add_argument("--intent", required=True, choices=sorted(INTENTS))
    n.add_argument("--to", required=True)
    n.add_argument("--title", required=True)
    n.add_argument("--repo")
    n.add_argument("--ref")
    n.add_argument("--re")
    n.add_argument("--task")
    n.add_argument("--expects", choices=sorted(EXPECTS))
    n.add_argument("--hop", type=int, default=0)
    n.set_defaults(fn=cmd_new)

    q = sub.add_parser("parse")
    q.add_argument("--sender-email", required=True)
    q.add_argument("--subject")
    q.set_defaults(fn=cmd_parse)

    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()

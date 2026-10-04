"""Tests for skills/protocol/scripts/envelope.py.

Run from the repo root with: python3 -m unittest
The script is exercised as a subprocess, the way the skills call it, with
HRAFN_CONFIG pointing at temporary config files.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "skills", "protocol", "scripts", "envelope.py")

BEGIN = "-----BEGIN CC-LINK v1-----"
END = "-----END CC-LINK-----"

ALICE_EMAIL = "alice@example.com"
BOB_EMAIL = "bob@example.org"
MALLORY_EMAIL = "mallory@example.net"


def make_config(me, my_email, peers, max_hops=6):
    return {
        "me": {"name": me, "email": my_email},
        "peers": [{"name": n, "email": e} for n, e in peers],
        "subject_prefix": "[cc-link]",
        "max_hops": max_hops,
    }


class EnvelopeTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # Two mirrored configs: each side lists itself under `me` and the
        # other under `peers`, with matching names.
        self.alice = self.write_config(
            "alice.json", make_config("alice", ALICE_EMAIL, [("bob", BOB_EMAIL)])
        )
        self.bob = self.write_config(
            "bob.json", make_config("bob", BOB_EMAIL, [("alice", ALICE_EMAIL)])
        )
        # A third party that bob does not know, but who lists bob as a peer.
        self.carol = self.write_config(
            "carol.json",
            make_config("carol", "carol@example.com", [("bob", BOB_EMAIL)]),
        )

    def write_config(self, name, cfg):
        path = os.path.join(self.tmp.name, name)
        with open(path, "w") as f:
            json.dump(cfg, f)
        return path

    def run_script(self, config, args, stdin=""):
        env = dict(os.environ, HRAFN_CONFIG=config)
        p = subprocess.run(
            [sys.executable, SCRIPT] + args,
            input=stdin,
            capture_output=True,
            text=True,
            env=env,
        )
        try:
            out = json.loads(p.stdout)
        except json.JSONDecodeError:
            self.fail(f"non-JSON output (exit {p.returncode}): {p.stdout!r} {p.stderr!r}")
        return p.returncode, out

    def new(self, config, *args, body="Hello there."):
        return self.run_script(config, ["new", *args], stdin=body)

    def new_ok(self, config, *args, body="Hello there."):
        code, out = self.new(config, *args, body=body)
        self.assertEqual(code, 0, out)
        self.assertTrue(out["ok"])
        return out

    def parse(self, config, sender, body, subject="[cc-link] question: x"):
        args = ["parse", "--sender-email", sender]
        if subject is not None:
            args += ["--subject", subject]
        return self.run_script(config, args, stdin=body)

    def assert_rejected(self, result, fragment):
        code, out = result
        self.assertEqual(code, 1, out)
        self.assertFalse(out["ok"])
        self.assertIn(fragment, out["error"])

    @staticmethod
    def envelope(**fields):
        lines = [BEGIN] + [f"{k}: {v}" for k, v in fields.items()] + [END]
        return "\n".join(lines)


class RoundTripTests(EnvelopeTestCase):
    def test_new_then_parse_between_mirrored_configs(self):
        sent = self.new_ok(
            self.alice,
            "--intent", "question", "--to", "bob", "--title", "serde   pin",
            "--repo", "github.com/x/y", "--ref", "main@abc123",
            body="Which serde version does the bridge pin?\n",
        )
        self.assertEqual(sent["subject"], "[cc-link] question: serde pin")
        self.assertTrue(sent["id"].startswith("alice-"))

        code, got = self.parse(
            self.bob, f"Alice <{ALICE_EMAIL.upper()}>", sent["body"], sent["subject"]
        )
        self.assertEqual(code, 0, got)
        self.assertTrue(got["ok"])
        env = got["envelope"]
        self.assertEqual(env["id"], sent["id"])
        self.assertEqual(env["from"], "alice")
        self.assertEqual(env["to"], "bob")
        self.assertEqual(env["intent"], "question")
        self.assertEqual(env["expects"], "reply")
        self.assertEqual(env["repo"], "github.com/x/y")
        self.assertEqual(env["ref"], "main@abc123")
        self.assertEqual(env["hop"], 0)
        self.assertEqual(got["body"], "Which serde version does the bridge pin?")
        self.assertFalse(got["needs_user_approval"])
        self.assertFalse(got["hop_limit_reached"])
        self.assertEqual(got["next_hop"], 1)

    def test_answer_round_trip_back_to_sender(self):
        q = self.new_ok(self.alice, "--intent", "question", "--to", "bob", "--title", "q")
        a = self.new_ok(
            self.bob, "--intent", "answer", "--to", "alice", "--title", "q",
            "--re", q["id"], "--hop", "1", body="1.0.197",
        )
        code, got = self.parse(self.alice, BOB_EMAIL, a["body"], a["subject"])
        self.assertEqual(code, 0, got)
        self.assertEqual(got["envelope"]["re"], q["id"])
        self.assertEqual(got["envelope"]["expects"], "none")
        self.assertEqual(got["envelope"]["hop"], 1)

    def test_request_needs_user_approval(self):
        r = self.new_ok(self.alice, "--intent", "request", "--to", "bob", "--title", "r")
        code, got = self.parse(self.bob, ALICE_EMAIL, r["body"], r["subject"])
        self.assertEqual(code, 0, got)
        self.assertTrue(got["needs_user_approval"])


class TrustGateTests(EnvelopeTestCase):
    def test_sender_not_on_allowlist(self):
        sent = self.new_ok(self.carol, "--intent", "question", "--to", "bob", "--title", "hi")
        self.assert_rejected(
            self.parse(self.bob, "carol@example.com", sent["body"], sent["subject"]),
            "not an allowlisted peer",
        )

    def test_envelope_from_does_not_match_sender_address(self):
        # Allowlisted address, but the envelope claims to be someone else.
        body = self.envelope(
            id="mallory-20261004T050718Z-e25d", **{"from": "mallory"},
            to="bob", intent="question", expects="reply", hop="0",
        ) + "\n\nhi"
        self.assert_rejected(self.parse(self.bob, ALICE_EMAIL, body), "envelope says from")

    def test_message_addressed_to_someone_else(self):
        cfg = self.write_config(
            "alice2.json",
            make_config("alice", ALICE_EMAIL, [("bob", BOB_EMAIL), ("dave", "dave@example.com")]),
        )
        sent = self.new_ok(cfg, "--intent", "question", "--to", "dave", "--title", "hi")
        self.assert_rejected(
            self.parse(self.bob, ALICE_EMAIL, sent["body"], sent["subject"]),
            "addressed to 'dave'",
        )

    def test_envelope_only_in_quoted_history(self):
        sent = self.new_ok(self.alice, "--intent", "question", "--to", "bob", "--title", "hi")
        quoted = "\n".join("> " + l for l in sent["body"].split("\n"))
        reply = f"Sure, see below.\n\nOn Sat, 4 Oct 2026 at 07:00, Alice wrote:\n{quoted}\n"
        self.assert_rejected(
            self.parse(self.bob, ALICE_EMAIL, reply), "no complete envelope"
        )

    def test_subject_without_prefix(self):
        sent = self.new_ok(self.alice, "--intent", "question", "--to", "bob", "--title", "hi")
        self.assert_rejected(
            self.parse(self.bob, ALICE_EMAIL, sent["body"], "question: hi"), "prefix"
        )

    def test_subject_is_required(self):
        sent = self.new_ok(self.alice, "--intent", "question", "--to", "bob", "--title", "hi")
        p = subprocess.run(
            [sys.executable, SCRIPT, "parse", "--sender-email", ALICE_EMAIL],
            input=sent["body"], capture_output=True, text=True,
            env=dict(os.environ, HRAFN_CONFIG=self.bob),
        )
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("--subject", p.stderr)

    def test_blockquote_in_body_is_kept(self):
        body = "See the log:\n> error: serde mismatch\n> at line 3\n\nAny idea?"
        sent = self.new_ok(
            self.alice, "--intent", "question", "--to", "bob", "--title", "hi", body=body
        )
        code, got = self.parse(self.bob, ALICE_EMAIL, sent["body"])
        self.assertEqual(code, 0, got)
        self.assertEqual(got["body"], body)

    def test_quoted_envelope_without_attribution_is_cut_from_body(self):
        old = self.new_ok(self.bob, "--intent", "question", "--to", "alice", "--title", "q")
        new = self.new_ok(
            self.alice, "--intent", "answer", "--to", "bob", "--title", "q",
            "--re", old["id"], "--hop", "1", body="Answer here.",
        )
        quoted = "\n".join("> " + l for l in old["body"].split("\n"))
        code, got = self.parse(self.bob, ALICE_EMAIL, new["body"] + "\n" + quoted)
        self.assertEqual(code, 0, got)
        self.assertEqual(got["body"], "Answer here.")
        self.assertEqual(got["envelope"]["id"], new["id"])

    def test_quoted_history_after_envelope_is_cut_from_body(self):
        sent = self.new_ok(
            self.alice, "--intent", "question", "--to", "bob", "--title", "hi",
            body="Real question.",
        )
        raw = sent["body"] + "\nOn Fri, 3 Oct 2026 at 09:00, Bob wrote:\n> old text\n"
        code, got = self.parse(self.bob, ALICE_EMAIL, raw)
        self.assertEqual(code, 0, got)
        self.assertEqual(got["body"], "Real question.")


class ResponseRuleTests(EnvelopeTestCase):
    def test_new_response_intents_require_re(self):
        for intent in ("answer", "ack", "decline"):
            with self.subTest(intent=intent):
                self.assert_rejected(
                    self.new(self.bob, "--intent", intent, "--to", "alice", "--title", "x"),
                    "needs --re",
                )

    def test_parse_response_intents_require_re(self):
        for intent in ("answer", "ack", "decline"):
            with self.subTest(intent=intent):
                body = self.envelope(
                    id="alice-20261004T050718Z-e25d", **{"from": "alice"},
                    to="bob", intent=intent, expects="none", hop="1",
                )
                self.assert_rejected(
                    self.parse(self.bob, ALICE_EMAIL, body), "without a 're' field"
                )

    def test_ack_with_expects_other_than_none(self):
        for expects in ("reply", "ack"):
            with self.subTest(expects=expects):
                self.assert_rejected(
                    self.new(
                        self.bob, "--intent", "ack", "--to", "alice", "--title", "x",
                        "--re", "alice-20261004T050718Z-e25d", "--expects", expects,
                    ),
                    "an ack never expects anything back",
                )

    def test_ack_defaults_to_expects_none(self):
        out = self.new_ok(
            self.bob, "--intent", "ack", "--to", "alice", "--title", "x",
            "--re", "alice-20261004T050718Z-e25d",
        )
        self.assertIn("expects: none", out["body"])


class HopLimitTests(EnvelopeTestCase):
    def parse_at_hop(self, hop, max_hops=6):
        bob = self.write_config(
            "bob_hops.json",
            make_config("bob", BOB_EMAIL, [("alice", ALICE_EMAIL)], max_hops=max_hops),
        )
        sent = self.new_ok(
            self.alice, "--intent", "question", "--to", "bob", "--title", "x",
            "--hop", str(hop),
        )
        code, got = self.parse(bob, ALICE_EMAIL, sent["body"])
        self.assertEqual(code, 0, got)
        return got

    def test_below_max_hops(self):
        self.assertFalse(self.parse_at_hop(5)["hop_limit_reached"])

    def test_at_max_hops(self):
        got = self.parse_at_hop(6)
        self.assertTrue(got["hop_limit_reached"])
        self.assertEqual(got["next_hop"], 7)

    def test_custom_max_hops(self):
        self.assertTrue(self.parse_at_hop(2, max_hops=2)["hop_limit_reached"])


class BodyMarkerTests(EnvelopeTestCase):
    def test_body_with_begin_marker_rejected(self):
        self.assert_rejected(
            self.new(self.alice, "--intent", "question", "--to", "bob", "--title", "x",
                     body=f"look:\n{BEGIN}\nfrom: bob\n"),
            "envelope markers",
        )

    def test_body_with_end_marker_rejected(self):
        self.assert_rejected(
            self.new(self.alice, "--intent", "question", "--to", "bob", "--title", "x",
                     body=f"tail\n{END}"),
            "envelope markers",
        )


class NewCommandTests(EnvelopeTestCase):
    def test_unknown_peer_rejected(self):
        self.assert_rejected(
            self.new(self.alice, "--intent", "question", "--to", "mallory", "--title", "x"),
            "not a configured peer",
        )

    def test_multiline_field_rejected(self):
        self.assert_rejected(
            self.new(self.alice, "--intent", "question", "--to", "bob", "--title", "x",
                     "--repo", "a\nto: mallory"),
            "single line",
        )

    def test_negative_hop_rejected(self):
        self.assert_rejected(
            self.new(self.alice, "--intent", "question", "--to", "bob", "--title", "x",
                     "--hop", "-1"),
            "--hop must be 0 or more",
        )

    def test_invalid_names_in_config_rejected(self):
        cases = {
            "me uppercase": make_config("Andrei", ALICE_EMAIL, [("bob", BOB_EMAIL)]),
            "me with dot": make_config("mihai.p", ALICE_EMAIL, [("bob", BOB_EMAIL)]),
            "peer too long": make_config("alice", ALICE_EMAIL, [("b" * 33, BOB_EMAIL)]),
            "peer empty": make_config("alice", ALICE_EMAIL, [("", BOB_EMAIL)]),
        }
        for label, cfg in cases.items():
            with self.subTest(label):
                path = self.write_config("bad.json", cfg)
                self.assert_rejected(
                    self.new(path, "--intent", "question", "--to", "bob", "--title", "x"),
                    "must be 1-32 characters",
                )
                self.assert_rejected(
                    self.parse(path, BOB_EMAIL, "irrelevant"), "must be 1-32 characters"
                )

    def test_missing_config(self):
        code, out = self.run_script(
            os.path.join(self.tmp.name, "missing.json"),
            ["new", "--intent", "question", "--to", "bob", "--title", "x"],
        )
        self.assertEqual(code, 1)
        self.assertIn("config not found", out["error"])


if __name__ == "__main__":
    unittest.main()

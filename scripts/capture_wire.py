#!/usr/bin/env python3
"""Capture what Claude Code puts on the wire for each --effort level.

Claude Code talks the Anthropic Messages API, so this starts a local stub server,
points a throwaway Claude Code session at it, and records the request body across
--effort low|medium|high|xhigh|max. Nothing leaves the machine and no real API key
is used: the stub answers every request with an error after logging it.

Usage:
    ./scripts/capture_wire.py [--claude ~/.local/bin/claude] [--model deepseek-v4-pro]
"""

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

EFFORTS = ["low", "medium", "high", "xhigh", "max"]

# Fields that matter for reasoning effort; everything else (user ids, metadata) is dropped
# before it is written to disk, so the captured file is safe to publish.
KEEP_FIELDS = ("model", "thinking", "output_config", "effort", "reasoning_effort", "max_tokens")


class Stub(BaseHTTPRequestHandler):
    seen = []

    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(n)
        try:
            body = json.loads(raw)
        except Exception:
            body = {}
        record = {k: body.get(k) for k in KEEP_FIELDS if k in body}
        Stub.seen.append(record)
        payload = json.dumps(
            {
                "type": "error",
                "error": {"type": "invalid_request_error", "message": "stub: request logged"},
            }
        ).encode()
        self.send_response(400)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


def start_stub():
    server = HTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def run_once(claude, model, effort, base_url, tmpdir):
    env = dict(os.environ)
    env.update(
        {
            "ANTHROPIC_BASE_URL": base_url,
            "ANTHROPIC_AUTH_TOKEN": "stub-token-not-a-real-key",
            "ANTHROPIC_DEFAULT_OPUS_MODEL": model,
            "ANTHROPIC_DEFAULT_SONNET_MODEL": model,
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": model,
            # Keep Claude Code's state out of ~/.claude and skip its updater.
            "CLAUDE_CONFIG_DIR": tmpdir,
            "DISABLE_AUTOUPDATER": "1",
            "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "1000000",
        }
    )
    env.pop("ANTHROPIC_API_KEY", None)
    before = len(Stub.seen)
    try:
        subprocess.run(
            [claude, "-p", "hi", "--model", model, "--effort", effort],
            env=env,
            capture_output=True,
            timeout=90,
            check=False,
        )
    except subprocess.TimeoutExpired:
        pass
    return Stub.seen[before] if len(Stub.seen) > before else None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--claude",
        default=shutil.which("claude") or os.path.expanduser("~/.local/bin/claude"),
        help="path to the claude binary (default: claude on PATH)",
    )
    ap.add_argument("--model", default="deepseek-v4-pro")
    ap.add_argument("--out", default="results/wire-format.jsonl")
    args = ap.parse_args()

    if not os.path.exists(args.claude):
        raise SystemExit(f"error: claude binary not found at {args.claude}")

    server = start_stub()
    base_url = f"http://127.0.0.1:{server.server_port}"
    tmpdir = tempfile.mkdtemp(prefix="claude-wire-")

    rows = []
    try:
        for effort in EFFORTS:
            record = run_once(args.claude, args.model, effort, base_url, tmpdir)
            rows.append({"requested_effort": effort, "request": record})
            sent = ((record or {}).get("output_config") or {}).get("effort")
            thinking = (record or {}).get("thinking") or {}
            print(
                f"--effort {effort:6} -> output_config.effort={sent!r:9} "
                f"thinking.type={thinking.get('type')!r} "
                f"thinking.display={thinking.get('display')!r}"
            )
    finally:
        server.shutdown()
        shutil.rmtree(tmpdir, ignore_errors=True)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, sort_keys=True) + "\n")
    print(f"\nwrote {args.out}")

    if all((r["request"] or {}).get("output_config") for r in rows):
        print(
            "\nEvery level is forwarded verbatim as output_config.effort; Claude Code does not\n"
            "clamp to the levels the gateway advertises."
        )


if __name__ == "__main__":
    main()

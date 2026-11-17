#!/usr/bin/env python3
"""Capture what OpenCode puts on the wire for each model variant.

OpenCode picks a variant with `-m provider/model#variant` and talks OpenAI Chat Completions
for these DeepSeek models. This starts a local stub, points the built-in `opencode-go`
provider at it through OPENCODE_CONFIG, and records the request body per variant. The stored
OpenCode credentials are never used: the request stops at the stub.

Usage:
    ./scripts/capture_wire_opencode.py [--opencode ~/.opencode/bin/opencode]
"""

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# The variants OpenCode's catalog exposes for these models.
VARIANTS = {
    "deepseek-v4-pro": ["high", "max"],
    "deepseek-v4.1-flash": ["low", "high", "max"],
}

# Fields that encode reasoning effort in the OpenAI-compatible request; everything else is
# dropped so the capture is safe to publish.
KEEP_FIELDS = (
    "model",
    "reasoning_effort",
    "reasoning",
    "thinking",
    "output_config",
    "max_tokens",
    "max_completion_tokens",
    "stream",
    "verbosity",
)


class Stub(BaseHTTPRequestHandler):
    seen = []

    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(n)
        try:
            body = json.loads(raw)
        except Exception:
            body = {}
        Stub.seen.append(
            {"path": self.path, **{k: body.get(k) for k in KEEP_FIELDS if k in body}}
        )
        payload = json.dumps(
            {"error": {"message": "stub: request logged", "type": "invalid_request_error"}}
        ).encode()
        self.send_response(400)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


def run_once(opencode, config_path, model, variant, tmpdir):
    env = dict(os.environ)
    env["OPENCODE_CONFIG"] = config_path
    before = len(Stub.seen)
    try:
        completed = subprocess.run(
            [opencode, "run", "--standalone", "--format", "json",
             "-m", f"opencode-go/{model}#{variant}", "--title", "wire capture", "hi"],
            env=env,
            capture_output=True,
            timeout=120,
            check=False,
            cwd=tmpdir,
        )
        output = (completed.stdout or b"").decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        output = ""
    request = Stub.seen[before] if len(Stub.seen) > before else None
    error = None
    if request is None:
        for line in output.splitlines():
            try:
                doc = json.loads(line)
            except Exception:
                continue
            if doc.get("type") == "error":
                error = (doc.get("error") or {}).get("message")
                break
    return request, error


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    default_bin = os.path.expanduser("~/.opencode/bin/opencode")
    ap.add_argument("--opencode", default=shutil.which("opencode") or default_bin)
    ap.add_argument("--out", default="results/wire-format-opencode.jsonl")
    args = ap.parse_args()

    if not os.path.exists(args.opencode):
        raise SystemExit(f"error: opencode binary not found at {args.opencode}")

    server = HTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_port

    tmpdir = tempfile.mkdtemp(prefix="opencode-wire-")
    config_path = os.path.join(tmpdir, "opencode.json")
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "$schema": "https://opencode.ai/config.json",
                "provider": {
                    "opencode-go": {"options": {"baseURL": f"http://127.0.0.1:{port}"}}
                },
            },
            f,
        )

    rows = []
    try:
        for model, variants in VARIANTS.items():
            for variant in variants:
                request, error = run_once(args.opencode, config_path, model, variant, tmpdir)
                rows.append(
                    {
                        "model": model,
                        "requested_variant": variant,
                        "request": request,
                        "error": error,
                    }
                )
                sent = (request or {}).get("reasoning_effort")
                path = (request or {}).get("path")
                print(
                    f"{model:22} #{variant:5} -> path={path!r} "
                    f"reasoning_effort={sent!r}"
                    + (f"  ({error})" if error else "")
                )
    finally:
        server.shutdown()
        shutil.rmtree(tmpdir, ignore_errors=True)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, sort_keys=True) + "\n")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Measure whether output_config.effort changes reasoning for OpenCode Go models.

Calls the Anthropic Messages endpoint behind OpenCode Go directly, once per
(model, effort, trial), and records the reasoning token count the gateway reports
(usage.output_tokens_details.thinking_tokens) plus output tokens and latency.

Results are appended to the output file one line at a time, so an interrupted run
still leaves usable data.

Usage:
    ./scripts/effort_matrix.py --trials 3
    ./scripts/effort_matrix.py --models deepseek-v4-pro --efforts low,max --trials 5
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

API_URL = "https://opencode.ai/inference/go/anthropic/v1/messages"
DEFAULT_KEY_FILE = os.path.expanduser("~/.config/opencode-go/key")
USER_AGENT = "opencode-go-effort-test/1.0"
DEFAULT_MODELS = ["deepseek-v4-pro", "deepseek-v4.1-flash"]
DEFAULT_EFFORTS = ["low", "medium", "high", "xhigh", "max"]
# Picking the prompt took three tries. It has to require real reasoning but finish well under
# the token cap, or the cap decides the length and the effort signal disappears:
#   987654321 * 123456789 with a cast-out-nines check  -> truncated at 4000 tokens
#   3x10 domino tilings (answer 571)                   -> truncated at 8000 tokens, even on low
#   the snail puzzle below                             -> 86-511 thinking tokens, never truncated
DEFAULT_PROMPT = (
    "A snail climbs 3 cm up a 10 cm pole each day and slips 2 cm each night. "
    "How many days does it take to reach the top? Explain briefly."
)
DEFAULT_EXPECT = "8"


def read_key(path):
    value = os.environ.get("OPENCODE_GO_KEY")
    if value:
        return value.strip()
    if not os.path.exists(path):
        sys.exit(
            f"error: no API key. Set OPENCODE_GO_KEY or put the key in {path}.\n"
            "Create a personal API key in the OpenCode Console (Account > Personal API keys)\n"
            "from a workspace subscribed to Go."
        )
    with open(path, encoding="utf-8") as f:
        value = f.read().strip()
    if not value.startswith("oc_sk_"):
        sys.exit(f"error: {path} does not look like an OpenCode API key (expected oc_sk_...)")
    return value


def call(key, model, effort, prompt, max_tokens, session, timeout):
    body = {
        "model": model,
        "max_tokens": max_tokens,
        # What Claude Code sends: adaptive thinking plus an effort hint.
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": effort},
        "messages": [{"role": "user", "content": prompt}],
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode(),
        headers={
            "authorization": f"Bearer {key}",
            "content-type": "application/json",
            "anthropic-version": "2023-06-01",
            "user-agent": USER_AGENT,
            "x-opencode-session": session,
        },
        method="POST",
    )
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = json.loads(r.read())
        status = r.status
    except urllib.error.HTTPError as e:
        raw = e.read() or b""
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"raw": raw.decode("utf-8", "replace")[:300]}
        status = e.code
    except Exception as e:  # timeouts, connection resets
        payload = {"raw": f"{type(e).__name__}: {e}"}
        status = 0
    elapsed = round(time.time() - started, 1)

    usage = payload.get("usage") or {}
    details = usage.get("output_tokens_details") or {}
    opencode = usage.get("opencode") or {}
    content = payload.get("content") or []
    text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
    gateway_thinking = details.get("thinking_tokens")
    opencode_thinking = (opencode.get("tokens") or {}).get("reasoning")
    error = None
    if status != 200:
        if "1010" in str(payload.get("raw", "")):
            error = "Cloudflare 1010: blocked client, set a descriptive User-Agent"
        elif payload.get("error"):
            error = json.dumps(payload["error"])[:200]
        else:
            error = str(payload.get("raw"))[:200]

    return {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "model": model,
        "effort": effort,
        "http": status,
        "stop_reason": payload.get("stop_reason"),
        # The two models expose reasoning tokens in different fields: pro fills
        # usage.output_tokens_details.thinking_tokens, flash fills usage.opencode.tokens.reasoning.
        # Keep both and record which one the combined value came from.
        "thinking_tokens_gateway": gateway_thinking,
        "thinking_tokens_opencode": opencode_thinking,
        "thinking_tokens": (
            gateway_thinking if gateway_thinking is not None else opencode_thinking
        ),
        "thinking_source": (
            "output_tokens_details" if gateway_thinking is not None
            else ("opencode.tokens" if opencode_thinking is not None else None)
        ),
        "thinking_chars": sum(
            len(b.get("thinking") or "") for b in content if b.get("type") == "thinking"
        ),
        "output_tokens": usage.get("output_tokens"),
        "cache_read_input_tokens": usage.get("cache_read_input_tokens"),
        "thinking_blocks": sum(1 for b in content if b.get("type") in ("thinking", "redacted_thinking")),
        "list_cost_usd": opencode.get("list_cost"),
        "seconds": elapsed,
        "answer": text[:400],
        "error": error,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--key-file", default=DEFAULT_KEY_FILE)
    ap.add_argument("--models", default=",".join(DEFAULT_MODELS))
    ap.add_argument("--efforts", default=",".join(DEFAULT_EFFORTS))
    ap.add_argument("--trials", type=int, default=3)
    ap.add_argument("--prompt", default=DEFAULT_PROMPT)
    ap.add_argument("--expect", default=DEFAULT_EXPECT,
                    help="string the answer should contain; '' disables the check")
    ap.add_argument("--max-tokens", type=int, default=8000)
    ap.add_argument("--timeout", type=int, default=240)
    ap.add_argument("--out", default="results/matrix.jsonl")
    args = ap.parse_args()

    key = read_key(args.key_file)
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    efforts = [e.strip() for e in args.efforts.split(",") if e.strip()]

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    total = len(models) * len(efforts) * args.trials
    done = 0
    print(f"{total} requests -> {args.out}\n")

    with open(args.out, "a", encoding="utf-8") as out:
        for model in models:
            for effort in efforts:
                # A stable session per (model, effort) lets the gateway reuse its prompt cache.
                session = f"ses_eff_{uuid.uuid4().hex[:16]}"
                for _ in range(args.trials):
                    row = call(key, model, effort, args.prompt, args.max_tokens,
                               session, args.timeout)
                    done += 1
                    row["answer_ok"] = (
                        None if not args.expect
                        else (args.expect in (row["answer"] or ""))
                    )
                    out.write(json.dumps(row, sort_keys=True) + "\n")
                    out.flush()
                    print(
                        f"[{done:>2}/{total}] {model:20} {effort:7} "
                        f"http={row['http']} think={str(row['thinking_tokens']):>5} "
                        f"out={str(row['output_tokens']):>5} stop={row['stop_reason']} "
                        f"{row['seconds']:>5}s ok={row['answer_ok']}"
                        + (f"  {row['error']}" if row["error"] else "")
                    )

    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Measure reasoning volume per OpenCode model variant, through the OpenCode CLI.

Runs `opencode run --format json` for each (model, variant, trial) and reads the token
counts OpenCode recorded in its local database (~/.local/share/opencode/opencode.db). That
database holds, per assistant message, `tokens.{input,output,reasoning,cache}`, the model and
variant used, the cost, and the reasoning text.

The `effort` field in each output row is the OpenCode variant name, so the same summarize.py
and compare.py work on this file and on the Claude Code results.

Usage:
    ./scripts/opencode_matrix.py --trials 5
    ./scripts/opencode_matrix.py --models deepseek-v4-pro --variants high,max --trials 10
"""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time

DEFAULT_OPENCODE = os.path.expanduser("~/.opencode/bin/opencode")
DEFAULT_DB = os.path.expanduser("~/.local/share/opencode/opencode.db")
DEFAULT_PROVIDER = "opencode-go"
# Variants the catalog exposes per model. OpenCode rejects anything else with
# "Variant unavailable", so these are also the only reachable effort levels here.
VARIANTS_BY_MODEL = {
    "deepseek-v4-pro": ["high", "max"],
    "deepseek-v4.1-flash": ["low", "high", "max"],
}
DEFAULT_PROMPT = (
    "A snail climbs 3 cm up a 10 cm pole each day and slips 2 cm each night. "
    "How many days does it take to reach the top? Explain briefly."
)
DEFAULT_EXPECT = "8"


def opencode_version(binary):
    try:
        out = subprocess.run(
            [binary, "--version"], capture_output=True, timeout=30, check=False
        )
        return (out.stdout or b"").decode("utf-8", "replace").strip().splitlines()[0]
    except Exception:
        return None


def parse_events(stdout):
    docs = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            docs.append(json.loads(line))
        except Exception:
            continue
    return docs


def answer_from(docs):
    return "".join(
        d.get("part", {}).get("text", "") for d in docs if d.get("type") == "text"
    )


def error_from(docs):
    for d in docs:
        if d.get("type") == "error":
            return (d.get("error") or {}).get("message") or "error"
    return None


def read_usage(db_path, session_id, model):
    """Sum tokens, cost, reasoning characters and model time for one session."""
    totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "thinking_tokens": 0,
        "cache_read_input_tokens": 0,
        "cost_usd": 0.0,
        "thinking_chars": 0,
        "model_ms": 0,
        "assistant_messages": 0,
    }
    if not session_id or not os.path.exists(db_path):
        return totals
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "select data from session_message where session_id=? and type='assistant' "
            "order by seq",
            (session_id,),
        ).fetchall()
    finally:
        con.close()

    for (raw,) in rows:
        try:
            doc = json.loads(raw)
        except Exception:
            continue
        if (doc.get("model") or {}).get("id") != model:
            continue
        totals["assistant_messages"] += 1
        tokens = doc.get("tokens") or {}
        totals["input_tokens"] += tokens.get("input") or 0
        totals["output_tokens"] += tokens.get("output") or 0
        totals["thinking_tokens"] += tokens.get("reasoning") or 0
        totals["cache_read_input_tokens"] += (tokens.get("cache") or {}).get("read") or 0
        totals["cost_usd"] += doc.get("cost") or 0.0
        totals["thinking_chars"] += sum(
            len(part.get("text") or "")
            for part in doc.get("content", [])
            if part.get("type") == "reasoning"
        )
        timing = doc.get("time") or {}
        if timing.get("created") and timing.get("completed"):
            totals["model_ms"] += timing["completed"] - timing["created"]
    return totals


def run_once(opencode, provider, model, variant, prompt, timeout, cwd):
    env = dict(os.environ)
    started = time.time()
    try:
        completed = subprocess.run(
            [opencode, "run", "--standalone", "--format", "json",
             "-m", f"{provider}/{model}#{variant}", "--title", "effort test", prompt],
            capture_output=True,
            timeout=timeout,
            check=False,
            cwd=cwd,
            env=env,
        )
        stdout = (completed.stdout or b"").decode("utf-8", "replace")
        stderr = (completed.stderr or b"").decode("utf-8", "replace")
        returncode = completed.returncode
    except subprocess.TimeoutExpired:
        stdout, stderr, returncode = "", "timeout", -1
    wall = round(time.time() - started, 1)
    docs = parse_events(stdout)
    session = next((d.get("sessionID") for d in docs if d.get("sessionID")), None)
    return docs, stdout, stderr, returncode, wall, session


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--opencode", default=DEFAULT_OPENCODE)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--provider", default=DEFAULT_PROVIDER)
    ap.add_argument("--models", default=",".join(VARIANTS_BY_MODEL))
    ap.add_argument("--variants", default=None,
                    help="override the variant list for every model "
                         "(default: the catalog variants per model)")
    ap.add_argument("--trials", type=int, default=5)
    ap.add_argument("--prompt", default=DEFAULT_PROMPT)
    ap.add_argument("--expect", default=DEFAULT_EXPECT,
                    help="string the answer should contain; '' disables the check")
    ap.add_argument("--timeout", type=int, default=240)
    ap.add_argument("--out", default="results/matrix-opencode.jsonl")
    args = ap.parse_args()

    if not os.path.exists(args.opencode):
        sys.exit(f"error: opencode binary not found at {args.opencode}")
    if not os.path.exists(args.db):
        sys.exit(f"error: OpenCode database not found at {args.db}")

    version = opencode_version(args.opencode)
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    override = [v.strip() for v in (args.variants or "").split(",") if v.strip()]
    plan = [
        (model, variant)
        for model in models
        for variant in (override or VARIANTS_BY_MODEL.get(model, []))
    ]
    total = len(plan) * args.trials
    print(f"opencode {version}, {total} requests -> {args.out}\n")

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "a", encoding="utf-8") as out:
        done = 0
        for model, variant in plan:
            for _ in range(args.trials):
                docs, stdout, stderr, returncode, wall, session = run_once(
                    args.opencode, args.provider, model, variant,
                    args.prompt, args.timeout, os.getcwd(),
                )
                usage = read_usage(args.db, session, model)
                answer = answer_from(docs)
                error = error_from(docs) or (stderr.strip()[:200] or None)
                row = {
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "harness": "opencode",
                    "harness_version": version,
                    "provider": args.provider,
                    "model": model,
                    "effort": variant,
                    "variant": variant,
                    "returncode": returncode,
                    "stop_reason": None,
                    "answer": answer[:400],
                    "answer_ok": None if not args.expect else (args.expect in answer),
                    "seconds": wall,
                    "error": error,
                }
                row.update(usage)
                out.write(json.dumps(row, sort_keys=True) + "\n")
                out.flush()
                done += 1
                print(
                    f"[{done:>2}/{total}] {model:20} {variant:6} "
                    f"think={row['thinking_tokens']:>5} chars={row['thinking_chars']:>5} "
                    f"out={row['output_tokens']:>4} {wall:>5}s ok={row['answer_ok']}"
                    + (f"  {error}" if error else "")
                )

    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()

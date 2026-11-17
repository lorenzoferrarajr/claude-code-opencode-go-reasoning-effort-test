#!/usr/bin/env python3
"""Compare reasoning-effort effects between Claude Code and OpenCode.

Reads one or more Claude Code result files (Anthropic-format calls) and the OpenCode result
file (CLI runs), pairs the same model and effort levels, and prints:

1. medians per harness/model/effort, for a like-for-like view of reasoning volume;
2. a permutation test on the effect of raising effort, per harness.

Usage:
    ./scripts/compare_harnesses.py
    ./scripts/compare_harnesses.py --pairs deepseek-v4.1-flash:low:max
"""

import argparse
import json
import os
import random
import statistics
import sys

from compare import permutation_p, usable

# Both files are produced by tests that use the same question and the same models, so the
# comparable pairs are: pro high->max (OpenCode has no low), flash low->max (both harnesses).
DEFAULT_PAIRS = "deepseek-v4-pro:high:max,deepseek-v4.1-flash:low:max"
DEFAULT_CLAUDE_FILES = "results/matrix-low-vs-max.jsonl,results/matrix-high-vs-max.jsonl"
DEFAULT_OPENCODE_FILE = "results/matrix-opencode.jsonl"


def load(path, harness):
    if not os.path.exists(path):
        sys.exit(
            f"error: {path} not found. Run the corresponding measurement first "
            f"(see the Makefile), or pass --claude/--opencode explicitly."
        )
    rows = []
    for line in open(path, encoding="utf-8"):
        if not line.strip():
            continue
        row = json.loads(line)
        row.setdefault("harness", harness)
        rows.append(row)
    return rows


def median(values):
    return statistics.median(values) if values else None


def money(row):
    return row.get("list_cost_usd") if row.get("list_cost_usd") is not None else row.get("cost_usd")


def summarise(rows):
    usable_rows = [
        r for r in rows
        if (r.get("http") == 200 if "http" in r else r.get("returncode") == 0)
        and r.get("stop_reason") != "max_tokens"
        and r.get("error") is None
    ]
    return {
        "n": len(usable_rows),
        "think": median([r.get("thinking_tokens") or 0 for r in usable_rows]),
        "chars": median([r.get("thinking_chars") or 0 for r in usable_rows]),
        "out": median([r.get("output_tokens") or 0 for r in usable_rows]),
        "cost": median([money(r) for r in usable_rows if money(r) is not None]),
    }


def pick_pair(sets, model, base, top):
    """Return the first row set that contains both levels for this model.

    Claude Code results live in per-experiment files (low-vs-max, high-vs-max); using the
    whole file that covers the pair keeps runs from different experiments out of one cell.
    """
    for rows in sets:
        efforts = {r["effort"] for r in rows if r["model"] == model}
        if base in efforts and top in efforts:
            return rows
    return []


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--claude", default=DEFAULT_CLAUDE_FILES,
                    help="comma-separated Claude Code result files")
    ap.add_argument("--opencode", default=DEFAULT_OPENCODE_FILE)
    ap.add_argument("--pairs", default=DEFAULT_PAIRS,
                    help="model:base:top,... pairs to compare")
    args = ap.parse_args()

    claude_sets = [
        load(path, "claude-code")
        for path in [p.strip() for p in args.claude.split(",") if p.strip()]
    ]
    opencode_sets = [load(args.opencode, "opencode")]
    sets_by_harness = {"claude-code": claude_sets, "opencode": opencode_sets}

    pairs = []
    for spec in args.pairs.split(","):
        model, base, top = spec.split(":")
        pairs.append((model, base, top))

    selection = {}
    for harness, sets in sets_by_harness.items():
        for model, base, top in pairs:
            selection[(harness, model, base, top)] = pick_pair(sets, model, base, top)

    print("| harness | model | effort | n | thinking tokens (median) | thinking chars (median) | output tokens (median) | cost per run (median) |")
    print("| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |")
    for harness in ("claude-code", "opencode"):
        for model, base, top in pairs:
            rows = selection[(harness, model, base, top)]
            for effort in (base, top):
                sel = [r for r in rows if r["model"] == model and r["effort"] == effort]
                if not sel:
                    continue
                s = summarise(sel)
                cost = "-" if s["cost"] is None else f"${s['cost']:.4f}"
                print(
                    f"| {harness} | {model} | {effort} | {s['n']} | "
                    f"{s['think']:.0f} | {s['chars']:.0f} | {s['out']:.0f} | {cost} |"
                )

    print()
    print("| model | effort raise | harness | base (mean ± sd) | top (mean ± sd) | delta | permutation p |")
    print("| --- | --- | --- | --- | --- | ---: | ---: |")
    rng = random.Random(20261117)
    for model, base, top in pairs:
        for harness in ("claude-code", "opencode"):
            rows = selection[(harness, model, base, top)]
            base_rows = [r for r in rows if r["model"] == model and r["effort"] == base]
            top_rows = [r for r in rows if r["model"] == model and r["effort"] == top]
            a, b = usable(base_rows), usable(top_rows)
            if not a or not b:
                print(f"| {model} | {base} -> {top} | {harness} | (missing) | | | |")
                continue

            def fmt(values):
                sd = statistics.stdev(values) if len(values) > 1 else 0.0
                return f"{statistics.fmean(values):.0f} ± {sd:.0f}, n={len(values)}"

            p = permutation_p(list(a), list(b), rng)
            print(
                f"| {model} | {base} -> {top} | {harness} | {fmt(a)} | {fmt(b)} | "
                f"{statistics.fmean(b) - statistics.fmean(a):+.0f} | {p:.3f} |"
            )


if __name__ == "__main__":
    main()

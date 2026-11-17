#!/usr/bin/env python3
"""Compare two effort levels per model with a permutation test.

Reasoning-token counts are noisy between identical trials, so a median from three runs
can point the wrong way. This answers the narrower question: is the difference between
two levels larger than the difference between runs of the same level?

Usage:
    ./scripts/compare.py low max [results/matrix-low-vs-max.jsonl]
"""

import json
import random
import statistics
import sys
from collections import defaultdict

PERMUTATIONS = 10000


def usable(rows):
    def ok(r):
        if "http" in r:
            return r["http"] == 200
        if "returncode" in r:
            return r["returncode"] == 0
        return True

    return [
        r["thinking_tokens"] or 0 for r in rows
        if ok(r) and r.get("stop_reason") != "max_tokens" and r["error"] is None
    ]


def permutation_p(a, b, rng):
    observed = abs(statistics.fmean(a) - statistics.fmean(b))
    pooled = a + b
    hits = 0
    for _ in range(PERMUTATIONS):
        rng.shuffle(pooled)
        diff = abs(statistics.fmean(pooled[: len(a)]) - statistics.fmean(pooled[len(a):]))
        if diff >= observed:
            hits += 1
    return (hits + 1) / (PERMUTATIONS + 1)


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    level_a, level_b = sys.argv[1], sys.argv[2]
    path = sys.argv[3] if len(sys.argv) > 3 else "results/matrix-low-vs-max.jsonl"

    grouped = defaultdict(lambda: defaultdict(list))
    for line in open(path, encoding="utf-8"):
        if not line.strip():
            continue
        row = json.loads(line)
        grouped[row["model"]][row["effort"]].append(row)

    rng = random.Random(20261117)
    print(f"| model | {level_a} thinking tokens (mean ± sd, n) | {level_b} thinking tokens (mean ± sd, n) | difference | permutation p |")
    print("| --- | --- | --- | ---: | ---: |")
    for model, by_effort in grouped.items():
        a, b = usable(by_effort[level_a]), usable(by_effort[level_b])
        if not a or not b:
            print(f"| {model} | missing | missing | - | - |")
            continue

        def fmt(values):
            sd = statistics.stdev(values) if len(values) > 1 else 0.0
            return f"{statistics.fmean(values):.0f} ± {sd:.0f}, n={len(values)}"

        p = permutation_p(list(a), list(b), rng)
        print(
            f"| {model} | {fmt(a)} | {fmt(b)} | "
            f"{statistics.fmean(b) - statistics.fmean(a):+.0f} | {p:.3f} |"
        )
    print(
        "\nA p-value near 1 means the two levels are indistinguishable: runs of the same level\n"
        "differ by as much as the levels differ from each other."
    )


if __name__ == "__main__":
    main()

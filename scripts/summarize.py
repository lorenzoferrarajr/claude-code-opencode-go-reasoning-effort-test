#!/usr/bin/env python3
"""Turn results/matrix.jsonl into a markdown table.

Excludes failed and truncated runs (stop_reason=max_tokens) because a truncated answer
says nothing about effort: the cap, not the effort setting, decided the length.
Prints medians so a single slow or chatty run does not dominate.

Usage:
    ./scripts/summarize.py [results/matrix.jsonl]
"""

import json
import statistics
import sys
from collections import OrderedDict


def median(values):
    return statistics.median(values) if values else None


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "results/matrix.jsonl"
    rows = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]

    groups = OrderedDict()
    for row in rows:
        groups.setdefault((row["model"], row["effort"]), []).append(row)

    print("| model | effort | n | thinking tokens (median) | thinking chars (median) | output tokens (median) | seconds (median) | correct |")
    print("| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |")
    for (model, effort), group in groups.items():
        usable = [
            r for r in group
            if r["http"] == 200 and r["stop_reason"] != "max_tokens" and r["error"] is None
        ]
        truncated = sum(1 for r in group if r["stop_reason"] == "max_tokens")
        failed = sum(1 for r in group if r["http"] != 200 or r["error"])
        think = median([r["thinking_tokens"] or 0 for r in usable])
        think_chars = median([r.get("thinking_chars") or 0 for r in usable])
        output = median([r["output_tokens"] or 0 for r in usable])
        secs = median([r["seconds"] for r in usable])
        correct = [r.get("answer_ok") for r in usable if r.get("answer_ok") is not None]
        correct_text = (
            f"{sum(1 for c in correct if c)}/{len(correct)}" if correct else "-"
        )
        notes = []
        if truncated:
            notes.append(f"{truncated} truncated")
        if failed:
            notes.append(f"{failed} failed")
        if notes:
            correct_text += " (" + ", ".join(notes) + ")"
        think_text = "-" if think is None else f"{think:.0f}"
        chars_text = "-" if think_chars is None else f"{think_chars:.0f}"
        output_text = "-" if output is None else f"{output:.0f}"
        secs_text = "-" if secs is None else f"{secs:.1f}"
        print(
            f"| {model} | {effort} | {len(usable)} | {think_text} | {chars_text} | "
            f"{output_text} | {secs_text} | {correct_text} |"
        )


if __name__ == "__main__":
    main()

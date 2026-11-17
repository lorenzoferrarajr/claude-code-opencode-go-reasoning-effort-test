#!/usr/bin/env python3
"""Show what the OpenCode Go gateway advertises for each model.

Fetches https://opencode.ai/inference/go/v1/models and prints the fields that matter
for reasoning-effort support: the model's context window and the effort levels it
advertises under capabilities.reasoning.effort.

Usage:
    ./scripts/list_models.py [--json PATH]
"""

import argparse
import json
import os
import sys
import urllib.request

BASE_URL = "https://opencode.ai/inference/go/v1/models"
DEFAULT_KEY_FILE = os.path.expanduser("~/.config/opencode-go/key")
USER_AGENT = "opencode-go-effort-test/1.0"


def read_key(path):
    """Read the API key from a file or the OPENCODE_GO_KEY environment variable."""
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


def fetch_models(key):
    req = urllib.request.Request(
        BASE_URL,
        headers={"authorization": f"Bearer {key}", "user-agent": USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--key-file", default=DEFAULT_KEY_FILE)
    ap.add_argument("--json", metavar="PATH", help="also write a sanitized copy here")
    args = ap.parse_args()

    key = read_key(args.key_file)
    payload = fetch_models(key)
    models = payload.get("data", payload)

    keep = []
    for m in models:
        cap = m.get("capabilities") or {}
        reasoning = cap.get("reasoning") or {}
        limit = m.get("limit") or {}
        cost = ((m.get("cost") or {}).get("text") or {})
        row = {
            "id": m.get("id"),
            "name": m.get("name"),
            "context_window": limit.get("context"),
            "max_output_tokens": limit.get("output"),
            "reasoning_supported": reasoning.get("supported"),
            "advertised_efforts": reasoning.get("effort"),
            "input_price_per_mtok": ((cost.get("input") or {}).get("price")),
            "output_price_per_mtok": ((cost.get("output") or {}).get("price")),
        }
        keep.append(row)

    print(f"{'model':24} {'context':>9} {'max_out':>8} {'reasoning':>9}  advertised efforts")
    for row in keep:
        print(
            f"{row['id']:24} {str(row['context_window']):>9} "
            f"{str(row['max_output_tokens']):>8} "
            f"{str(row['reasoning_supported']):>9}  "
            f"{', '.join(row['advertised_efforts'] or []) or '(none)'}"
        )
    print(
        "\nNote: these lists are advisory. The gateway accepted every Claude Code effort\n"
        "level (low, medium, high, xhigh, max) for both models; see README results."
    )

    if args.json:
        os.makedirs(os.path.dirname(os.path.abspath(args.json)), exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"models": keep}, f, indent=1)
            f.write("\n")
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()

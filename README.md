# Reasoning effort in Claude Code on OpenCode Go

Does Claude Code's `--effort` setting (`low`, `medium`, `high`, `xhigh`, `max`) actually do
anything when Claude Code is pointed at the [OpenCode Go](https://opencode.ai/docs/console/go)
gateway, and which levels do the DeepSeek models behind it honour?

This repo records the investigation: what Claude Code puts on the wire, what the gateway
advertises, and what the reasoning token counts show when each level is exercised against each
model.

## Short answer

| Question | Answer |
| --- | --- |
| Does Claude Code forward effort to the gateway? | Yes, verbatim, as `output_config.effort`, alongside `thinking: {type: "adaptive"}`. It does not clamp to the levels the model advertises. |
| Does the gateway reject levels a model does not advertise? | No. Every level returned HTTP 200 for both models, including `medium`/`xhigh`/`low` on models that do not list them. |
| Does the level change reasoning? | Yes. `low` → `max` adds **+218 reasoning tokens** on `deepseek-v4-pro` (222 → 440, permutation p = 0.001) and **+79** on `deepseek-v4.1-flash` (189 → 268, p = 0.022), 10 trials per cell. |
| Is `xhigh` a distinct level? | Not measurably on `deepseek-v4-pro`: `xhigh` 332 ± 101 vs `max` 431 ± 236 thinking tokens, p = 0.245 (10 trials each). Treat them as interchangeable. |
| Which levels are worth using? | `low` for cheap/fast turns, `max` when the extra thinking is worth roughly double the reasoning tokens. `deepseek-v4-pro` responds about three times more strongly than `flash`. The power of intermediate levels (`medium`, `high`, `xhigh`) was not established: three trials per cell cannot order them. |

Measured with Claude Code `2.1.326` on 2026-11-17 against
`https://opencode.ai/inference/go/anthropic`.

## Background

Claude Code speaks the Anthropic Messages API. Pointed at a gateway, it sends the effort hint
inside the request body:

```json
{
  "model": "deepseek-v4-pro",
  "max_tokens": 32000,
  "thinking": { "type": "adaptive", "display": "omitted" },
  "output_config": { "effort": "high" }
}
```

The OpenCode Go models endpoint (`/inference/go/v1/models`) advertises a narrower set per model:

| Model | Context | Max output | Advertised efforts | Input / output price (per Mtok) |
| --- | ---: | ---: | --- | --- |
| `deepseek-v4-pro` | 1,000,000 | 384,000 | `high`, `max` | $0.66 / $1.98 |
| `deepseek-v4.1-flash` | 1,000,000 | 384,000 | `low`, `high`, `max` | $0.15 / $0.60 |

That mismatch is the question: is `--effort low` silently ignored on a model whose metadata
starts at `high`, and does `max` genuinely spend more reasoning tokens than `low`?

## Reproduce

Requirements: Python 3.9+ (standard library only, no packages), Claude Code for the wire capture,
and an OpenCode API key from a workspace subscribed to Go.

```bash
git clone git@github.com:lorenzoferrarajr/claude-code-opencode-go-reasoning-effort-test.git
cd claude-code-opencode-go-reasoning-effort-test

export OPENCODE_GO_KEY=oc_sk_...        # or put the key in ~/.config/opencode-go/key

make models    # what the gateway advertises
make wire      # what Claude Code sends for each --effort level (local stub, no key needed)
make matrix    # exploratory: 2 models x 5 levels x 3 trials
make table     # print the result table
make powered   # low vs max, 10 trials per cell, with a permutation test
make xhigh     # xhigh vs max on deepseek-v4-pro, 10 trials per cell
```

`make matrix` takes 5-10 minutes and costs a few cents of Go allowance: 30 requests with a
bounded prompt. Every request is appended to `results/matrix.jsonl` immediately, so an
interrupted run keeps its data. `make powered` and `make xhigh` are another 40 and 20 requests.
Lower `--trials` for a quick smoke test, raise it for tighter confidence intervals.

Individual runs:

```bash
./scripts/effort_matrix.py --models deepseek-v4-pro --efforts high,max --trials 5
./scripts/effort_matrix.py --prompt "your question" --expect "expected substring" --max-tokens 4000
./scripts/capture_wire.py --claude ~/.local/bin/claude --model deepseek-v4.1-flash
```

## Results

Columns: **thinking tokens** is the reasoning token count for the response, taken from
`usage.output_tokens_details.thinking_tokens` on `deepseek-v4-pro` and from
`usage.opencode.tokens.reasoning` on `deepseek-v4.1-flash` (the two models report it in
different fields; see Method notes). **thinking chars** is the length of the returned thinking
text and cross-checks the token counts. **output tokens** is `usage.output_tokens`, reasoning
plus visible answer. Truncated runs (`stop_reason: max_tokens`) and errors are excluded: the
cap, not the effort setting, decides their length.

### Exploratory matrix, 3 trials per cell

Every request succeeded and every answer was correct, which answers the "is it supported"
question. It does not order the levels: run-to-run variance is large, and the medians are not
monotonic. On `deepseek-v4-pro` the `max` median (185) sits *below* the `low` median (218), which
is noise, not a real inversion.

| model | effort | n | thinking tokens (median) | thinking chars (median) | output tokens (median) | seconds (median) | correct |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| deepseek-v4-pro | low | 3 | 218 | 672 | 288 | 3.7 | 3/3 |
| deepseek-v4-pro | medium | 3 | 264 | 807 | 347 | 4.0 | 3/3 |
| deepseek-v4-pro | high | 3 | 371 | 1123 | 440 | 4.6 | 3/3 |
| deepseek-v4-pro | xhigh | 3 | 366 | 1094 | 441 | 4.5 | 3/3 |
| deepseek-v4-pro | max | 3 | 185 | 551 | 261 | 3.5 | 3/3 |
| deepseek-v4.1-flash | low | 3 | 204 | 657 | 272 | 4.6 | 3/3 |
| deepseek-v4.1-flash | medium | 3 | 286 | 809 | 352 | 5.3 | 3/3 |
| deepseek-v4.1-flash | high | 3 | 131 | 425 | 189 | 4.0 | 3/3 |
| deepseek-v4.1-flash | xhigh | 3 | 209 | 590 | 254 | 4.3 | 3/3 |
| deepseek-v4.1-flash | max | 3 | 327 | 991 | 386 | 6.3 | 3/3 |

### Powered comparison, `low` vs `max`, 10 trials per cell

| model | effort | n | thinking tokens (median) | output tokens (median) | seconds (median) | correct |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| deepseek-v4-pro | low | 10 | 202 | 274 | 3.7 | 10/10 |
| deepseek-v4-pro | max | 10 | 454 | 527 | 5.2 | 10/10 |
| deepseek-v4.1-flash | low | 10 | 178 | 239 | 4.4 | 10/10 |
| deepseek-v4.1-flash | max | 10 | 252 | 311 | 5.8 | 10/10 |

Permutation test on the thinking-token counts (10,000 shuffles, seed 20261117):

| model | low (mean ± sd) | max (mean ± sd) | difference | permutation p |
| --- | --- | --- | ---: | ---: |
| deepseek-v4-pro | 222 ± 72, n=10 | 440 ± 167, n=10 | +218 | 0.001 |
| deepseek-v4.1-flash | 189 ± 57, n=10 | 268 ± 82, n=10 | +79 | 0.022 |

What this supports:

- **Effort is honoured, not ignored.** On both models `max` produces substantially more
  reasoning than `low`, and the difference is larger than the spread within either level.
- **The effect is much stronger on `deepseek-v4-pro`.** It nearly doubles its reasoning (222 →
  440 tokens, +98%) where `flash` adds about 40% (189 → 268). That also matches the models'
  advertised metadata, where `pro` starts at `high` rather than `low`.
- **Variance is large in absolute terms.** `pro` at `max` ranged from 169 to 800 thinking
  tokens, sd 167. A single run tells you almost nothing about the level; that is why the
  3-trial table looks unordered.
- **Latency follows reasoning volume loosely.** `pro` goes from 3.7 s to 5.2 s, `flash` from
  4.4 s to 5.8 s. Network noise dominates small differences.
- **Correctness did not change.** All 90 requests answered the puzzle correctly at every
  level, so on an easy task effort buys depth, not accuracy. A task near the model's limit
  would be the place to look for an accuracy effect.

### Is `xhigh` a distinct level? `xhigh` vs `max` on `deepseek-v4-pro`, 10 trials per cell

| effort | thinking tokens (mean ± sd) | median | output tokens (median) | seconds (median) | correct |
| --- | --- | ---: | ---: | ---: | --- |
| `xhigh` | 332 ± 101, n=10 | 294 | 369 | 4.2 | 10/10 |
| `max` | 431 ± 236, n=10 | 342 | 425 | 4.7 | 10/10 |

Difference +99 tokens, permutation p = 0.245. With this sample size `xhigh` is not
distinguishable from `max`: either the gateway maps both to the same internal level, or the
difference is smaller than the run-to-run spread. `max` itself varied from 169 to 800 tokens,
which is what makes the test insensitive. Treat `xhigh` and `max` as interchangeable on this
model unless you have evidence otherwise.

## Method notes

- **Bounded task.** The prompt (the snail puzzle, answer `8`) needs real reasoning but finishes
  well under `max_tokens=16000`. Two earlier prompts failed as measurements:
  `987654321 * 123456789` plus a cast-out-nines check truncates at 4000 tokens, and counting
  3x10 domino tilings (answer 571) truncates at 8000 tokens *even at `low`*, because DeepSeek
  keeps thinking until the cap. When runs hit the cap, the cap decides the length and the
  effort signal disappears.
- **Two places for reasoning tokens.** `deepseek-v4-pro` fills
  `usage.output_tokens_details.thinking_tokens`; `deepseek-v4.1-flash` leaves that field out and
  reports `usage.opencode.tokens.reasoning` instead. Reading only one field makes `flash` look
  like it does not reason at all. The scripts record both, plus `thinking_chars`.
- **Intermediate levels need more trials.** Three trials per cell cannot order `medium`,
  `high` and `xhigh`; the exploratory medians are non-monotonic. Only `low` vs `max` is powered
  here (10 trials per cell). Increasing `--trials` is the whole fix.
- **Adaptive thinking.** Claude Code sends `thinking: {type: "adaptive"}`, not a fixed
  `budget_tokens`. The model decides how much to think, and effort caps it, so token counts
  vary between identical trials even at a fixed level.
- **Thinking text comes back in raw calls.** Claude Code asks for `display: "omitted"`, so its
  sessions never show reasoning. The direct calls here omit the `display` field, so the gateway
  returns the thinking text; `thinking_chars` records its length and tracks the token counts.
  Only counts are committed, no reasoning content.
- **Prompt caching.** Trials within a model/level share one `x-opencode-session`, so input is
  cached between trials and latency figures are not skewed by one cold request.
- **Cloudflare and default User-Agents.** `urllib`'s default User-Agent is answered with
  `403` and `error code: 1010`. The scripts send `opencode-go-effort-test/1.0`; any descriptive
  User-Agent works. Claude Code's own User-Agent is accepted.
- **`--effort` vs `effortLevel`.** The flag overrides the `effortLevel` setting for the session;
  everything here uses the flag, so the numbers apply to both.
- **Latency is indicative.** Even at 10 trials per cell, network variance dominates differences
  under a second or two.
- **Session header.** Raw calls send `x-opencode-session`; the Go docs require it for clients
  that do not send a native session header. Claude Code does, so its requests need no extra
  header.

## Repo layout

```
scripts/list_models.py       # advertised metadata per model
scripts/capture_wire.py      # local stub + Claude Code, captures the request body per effort level
scripts/effort_matrix.py     # the measurement, writes JSONL incrementally
scripts/summarize.py         # JSONL -> markdown table
scripts/compare.py           # two levels -> permutation test
results/models.json          # sanitized models response
results/wire-format.jsonl    # captured request bodies (no ids, no credentials)
results/matrix.jsonl         # exploratory matrix, 3 trials per cell
results/matrix-low-vs-max.jsonl   # powered low vs max, 10 trials per cell
results/matrix-xhigh-vs-max.jsonl # xhigh vs max on deepseek-v4-pro
Makefile                     # models / wire / matrix / table / powered / xhigh
```

## Privacy

The scripts read the API key from `OPENCODE_GO_KEY` or `~/.config/opencode-go/key`, keep it in
memory, and never print or store it. `capture_wire.py` sends a placeholder token to a local stub
and never contacts OpenCode. Captured bodies keep only the fields under test (model, thinking,
`output_config`, `max_tokens`): Claude Code's `metadata` block, which carries a device id, is
dropped before anything is written. `results/` contains no account, session or device ids.

# Reasoning effort in Claude Code and OpenCode on OpenCode Go

Does Claude Code's `--effort` setting (`low`, `medium`, `high`, `xhigh`, `max`) — and
OpenCode's model variant (`-m model#variant`) — actually do anything when those harnesses are
pointed at the [OpenCode Go](https://opencode.ai/docs/console/go) gateway? And do the two
harnesses behave the same way on the same DeepSeek models?

This repo records the investigation: what each harness puts on the wire, what the gateway
advertises, and what the reasoning token counts show when each level is exercised.

## Short answer

| Question | Answer |
| --- | --- |
| Does Claude Code forward effort to the gateway? | Yes, verbatim, as `output_config.effort`, alongside `thinking: {type: "adaptive"}`. It does not clamp to the levels the model advertises. |
| Does the gateway reject levels a model does not advertise? | No. Every level returned HTTP 200 for both models, including `medium`/`xhigh`/`low` on models that do not list them. |
| Does OpenCode accept the same levels? | No. OpenCode gates variants client-side: `deepseek-v4-pro` offers `high`/`max`, `deepseek-v4.1-flash` offers `low`/`high`/`max`, and anything else fails with `Variant unavailable` before a request is made. It sends the variant as `reasoning_effort` over OpenAI Chat Completions. |
| Do the two harnesses agree? | Yes on direction, no on magnitude. Both raise reasoning with effort (flash `low` → `max`: Claude Code +79 tokens, p = 0.024; OpenCode +40, p = 0.012), but OpenCode produces **roughly half** the reasoning tokens at the same nominal level (pro `high`: 322 vs 186 median). |
| Does the level change reasoning? | Yes. Claude Code, `low` → `max`: **+218 reasoning tokens** on `deepseek-v4-pro` (222 → 440, p = 0.001) and **+79** on `deepseek-v4.1-flash` (189 → 268, p = 0.022), 10 trials per cell. |
| Is `xhigh` a distinct level? | Not measurably on `deepseek-v4-pro`: `xhigh` 332 ± 101 vs `max` 431 ± 236 thinking tokens, p = 0.245 (10 trials each). Treat them as interchangeable. |

Claude Code measurements: Claude Code `2.1.326`, 2026-11-17.
OpenCode measurements: OpenCode `2.1.4`, 2026-11-17.
Both against `https://opencode.ai/inference/go`.

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

OpenCode uses the model variant instead (`-m opencode-go/deepseek-v4-pro#high`). For these
DeepSeek models it talks OpenAI Chat Completions, so the same hint arrives in a different field:

```json
{
  "model": "deepseek-v4-pro",
  "max_completion_tokens": 256000,
  "reasoning_effort": "high",
  "stream": true
}
```

Both bodies are captured by `scripts/capture_wire.py` and `scripts/capture_wire_opencode.py`
against a local stub, not hand-written.

The OpenCode Go models endpoint (`/inference/go/v1/models`) advertises a narrower set per model:

| Model | Context | Max output | Advertised efforts | Input / output price (per Mtok) |
| --- | ---: | ---: | --- | --- |
| `deepseek-v4-pro` | 1,000,000 | 384,000 | `high`, `max` | $0.66 / $1.98 |
| `deepseek-v4.1-flash` | 1,000,000 | 384,000 | `low`, `high`, `max` | $0.15 / $0.60 |

That mismatch is the question: are lower or higher levels silently ignored, and does `max`
genuinely spend more reasoning tokens than the cheapest level available?

## Reproduce

Requirements: Python 3.9+ (standard library only, no packages), Claude Code for the wire capture,
and an OpenCode API key from a workspace subscribed to Go.

```bash
git clone git@github.com:lorenzoferrarajr/claude-code-opencode-go-reasoning-effort-test.git
cd claude-code-opencode-go-reasoning-effort-test

export OPENCODE_GO_KEY=oc_sk_...        # or put the key in ~/.config/opencode-go/key

make models          # what the gateway advertises
make wire            # what Claude Code sends for each --effort level (local stub, no key needed)
make matrix          # Claude Code: exploratory, 2 models x 5 levels x 3 trials
make table           # print the result table
make powered         # Claude Code: low vs max, 10 trials per cell, with a permutation test
make xhigh           # Claude Code: xhigh vs max on deepseek-v4-pro
make wire-opencode   # what OpenCode sends for each variant (local stub, no key needed)
make matrix-opencode # OpenCode: catalog variants x 10 trials
make compare         # Claude Code vs OpenCode, matched pairs
```

`make matrix-opencode` drives the real OpenCode CLI, so OpenCode must be authenticated to Go
(`opencode auth list` shows `OpenCode Go stored`). It reads token counts from OpenCode's local
database (`~/.local/share/opencode/opencode.db`), not from the CLI output.

`make matrix` takes 5-10 minutes and costs a few cents of Go allowance: 30 requests with a
bounded prompt. Every request is appended to `results/matrix.jsonl` immediately, so an
interrupted run keeps its data. `make powered` and `make xhigh` are another 40 and 20 requests,
`make matrix-opencode` another 150 (about 15 minutes). Lower `--trials` for a quick smoke test,
raise it for tighter confidence intervals.

Individual runs:

```bash
./scripts/effort_matrix.py --models deepseek-v4-pro --efforts high,max --trials 5
./scripts/effort_matrix.py --prompt "your question" --expect "expected substring" --max-tokens 4000
./scripts/capture_wire.py --claude ~/.local/bin/claude --model deepseek-v4.1-flash
./scripts/opencode_matrix.py --models deepseek-v4.1-flash --variants low,max --trials 5
```

Individual runs:

```bash
./scripts/effort_matrix.py --models deepseek-v4-pro --efforts high,max --trials 5
./scripts/effort_matrix.py --prompt "your question" --expect "expected substring" --max-tokens 4000
./scripts/capture_wire.py --claude ~/.local/bin/claude --model deepseek-v4.1-flash
```

## Claude Code results

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
- **Correctness did not change.** All 110 Claude Code requests answered the puzzle correctly at
  every level, so on an easy task effort buys depth, not accuracy. A task near the model's limit
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

### Matched run for the harness comparison: `high` vs `max` on `deepseek-v4-pro`

OpenCode cannot select `low` on `pro`, so the like-for-like pair is `high` → `max`. Ten trials
per cell, same protocol: median thinking tokens 322 → 420 (means 338 ± 125 → 404 ± 160,
+67, p = 0.310). The step is small enough that 10 trials do not separate it from noise; the
comparison below uses it anyway because it is the only pair both harnesses can reach.

## OpenCode results

OpenCode exposes only the variants its catalog lists, so the reachable levels are
`deepseek-v4-pro#high`, `#max`, and `deepseek-v4.1-flash#low`, `#high`, `#max`. Driven through the
CLI (`opencode run --standalone --format json`), with token counts read from OpenCode's local
database: 30 trials per cell.

| model | effort | n | thinking tokens (median) | thinking chars (median) | output tokens (median) | seconds (median) | correct |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| deepseek-v4-pro | high | 30 | 186 | 508 | 82 | 5.3 | 30/30 |
| deepseek-v4-pro | max | 30 | 210 | 599 | 77 | 5.7 | 30/30 |
| deepseek-v4.1-flash | low | 30 | 108 | 303 | 104 | 5.2 | 30/30 |
| deepseek-v4.1-flash | high | 30 | 138 | 377 | 102 | 5.8 | 30/30 |
| deepseek-v4.1-flash | max | 30 | 132 | 386 | 102 | 5.3 | 30/30 |

All 150 runs succeeded and answered correctly. `flash` is non-monotonic on medians
(`high` 138 > `max` 132), a reminder that even 30 trials leave wide intervals; the
permutation test on `low` vs `max` is the reliable comparison.

## Claude Code vs OpenCode

Medians for the matched pairs. `n` differs: Claude Code cells come from 10-trial runs,
OpenCode cells from 30-trial runs.

| harness | model | effort | n | thinking tokens (median) | thinking chars (median) | output tokens (median) | cost per run (median) |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| claude-code | deepseek-v4-pro | high | 10 | 322 | 1021 | 395 | $0.0009 |
| claude-code | deepseek-v4-pro | max | 10 | 420 | 1365 | 494 | $0.0010 |
| claude-code | deepseek-v4.1-flash | low | 10 | 178 | 572 | 239 | $0.0002 |
| claude-code | deepseek-v4.1-flash | max | 10 | 252 | 758 | 311 | $0.0002 |
| opencode | deepseek-v4-pro | high | 30 | 186 | 508 | 82 | $0.0009 |
| opencode | deepseek-v4-pro | max | 30 | 210 | 599 | 77 | $0.0010 |
| opencode | deepseek-v4.1-flash | low | 30 | 108 | 303 | 104 | $0.0013 |
| opencode | deepseek-v4.1-flash | max | 30 | 132 | 386 | 102 | $0.0003 |

Effect of raising effort, permutation test on thinking tokens:

| model | effort raise | harness | base (mean ± sd) | top (mean ± sd) | delta | permutation p |
| --- | --- | --- | --- | --- | ---: | ---: |
| deepseek-v4-pro | high → max | claude-code | 338 ± 125, n=10 | 404 ± 160, n=10 | +67 | 0.310 |
| deepseek-v4-pro | high → max | opencode | 165 ± 113, n=30 | 218 ± 76, n=30 | +53 | 0.042 |
| deepseek-v4.1-flash | low → max | claude-code | 189 ± 57, n=10 | 268 ± 82, n=10 | +79 | 0.024 |
| deepseek-v4.1-flash | low → max | opencode | 110 ± 46, n=30 | 150 ± 73, n=30 | +40 | 0.012 |

### What the comparison supports

- **Effort works in both harnesses.** Every cell raises reasoning when the level goes up, and
  the effect is significant for `flash` in both, and for `pro high → max` in OpenCode (Claude
  Code's 10-trial `pro` run is underpowered for that smaller step: +67, p = 0.31).
- **OpenCode reasons substantially less at the same nominal level.** Median thinking tokens are
  40-50% lower in every matched cell: `pro high` 322 → 186, `pro max` 420 → 210, `flash low`
  178 → 108, `flash max` 252 → 132. Thinking characters drop in the same proportion, so it is
  not a token-accounting artefact. The likely causes are the different harness scaffolding
  (about 8k input tokens for OpenCode against 12.6k for Claude Code, so a different system
  prompt and tool set) and the different API translation path.
- **The relative lift is similar.** `flash low → max` is +42% for Claude Code and +36% for
  OpenCode; `pro high → max` is +20% and +32%. Effort scales thinking in both; OpenCode just
  starts from a lower base.
- **The level menu differs.** OpenCode refuses `low`/`medium`/`xhigh` on `deepseek-v4-pro` and
  `medium`/`xhigh`/`none` on `flash` before making a request, while Claude Code forwards all
  five values and the gateway accepts them. Fine-grained control is a Claude Code advantage;
  a lower reasoning footprint is an OpenCode one.
- **What this does not measure.** Answer quality. All 260 runs across both harnesses answered the
  puzzle correctly, so the comparison says nothing about whether OpenCode's lower reasoning
  volume costs depth on harder work.

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
- **Two harnesses, two APIs.** Claude Code speaks Anthropic Messages (`output_config.effort`);
  OpenCode speaks OpenAI Chat Completions for these models (`reasoning_effort`). Same gateway,
  same models, different translation path, which is the point of the comparison.
- **Where OpenCode numbers come from.** `opencode run --format json` prints the answer and the
  session id but not token usage, so `scripts/opencode_matrix.py` reads the assistant messages
  OpenCode stores in `~/.local/share/opencode/opencode.db`: `tokens.{input,output,reasoning}`,
  `cost`, the model and variant, and the reasoning text. Messages are filtered by model id, and
  `--title` is passed so OpenCode does not spend a title-generation call on the session.
- **OpenCode wall time includes its CLI startup.** `--standalone` starts a private server per
  run; that overhead (roughly 1-2 s) is inside the seconds column. Compare thinking volume
  across harnesses, not latency.
- **Claude Code numbers are raw calls, not CLI runs.** `claude -p --output-format json` does not
  report thinking tokens, and Claude Code asks the gateway for `display: "omitted"`, so its
  reasoning text never comes back either. The direct calls here reproduce the request body the
  wire capture recorded, which is what makes the token counts available.
- **Different system prompts inflate input tokens, not reasoning.** An OpenCode run sends about
  8k input tokens (its harness prompt and tools); a Claude Code call about 12.6k. That affects
  cost per run, not the reasoning counts the comparison uses.
- **Output tokens are not comparable across harnesses.** The Anthropic `usage.output_tokens`
  includes thinking tokens. On the OpenAI path the gateway reports `completion_tokens`
  including reasoning plus `completion_tokens_details.reasoning_tokens`, and OpenCode stores
  `tokens.output` net of reasoning. The comparison therefore uses reasoning tokens and
  reasoning characters only; the output column is there for completeness, per harness.
- **OpenCode gates variants client-side.** `-m opencode-go/deepseek-v4-pro#low` fails with
  `Variant unavailable` before any request is made, and so do `medium`, `xhigh` and `none`. The
  catalog lists exactly the efforts the models endpoint advertises.
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
scripts/list_models.py            # advertised metadata per model
scripts/capture_wire.py           # Claude Code + local stub: request body per --effort level
scripts/capture_wire_opencode.py  # OpenCode + local stub: request body per variant
scripts/effort_matrix.py          # Claude Code path: Anthropic-format measurement
scripts/opencode_matrix.py        # OpenCode path: CLI runs, usage from OpenCode's database
scripts/summarize.py              # JSONL -> markdown table
scripts/compare.py                # two levels -> permutation test
scripts/compare_harnesses.py      # Claude Code vs OpenCode, matched pairs
results/models.json               # sanitized models response
results/wire-format.jsonl         # Claude Code request bodies (no ids, no credentials)
results/wire-format-opencode.jsonl# OpenCode request bodies
results/matrix.jsonl              # Claude Code exploratory matrix, 3 trials per cell
results/matrix-low-vs-max.jsonl   # Claude Code low vs max, 10 trials per cell
results/matrix-high-vs-max.jsonl  # Claude Code high vs max on deepseek-v4-pro
results/matrix-xhigh-vs-max.jsonl # Claude Code xhigh vs max on deepseek-v4-pro
results/matrix-opencode.jsonl     # OpenCode catalog variants, 10 trials per cell
Makefile                          # models / wire / matrix / powered / xhigh / *-opencode / compare
```

## Privacy

The scripts read the API key from `OPENCODE_GO_KEY` or `~/.config/opencode-go/key`, keep it in
memory, and never print or store it. `capture_wire.py` and `capture_wire_opencode.py` send a
placeholder token to a local stub and never contact OpenCode. Captured bodies keep only the
fields under test (model, effort, thinking, token caps): Claude Code's `metadata` block, which
carries a device id, is dropped before anything is written. `opencode_matrix.py` reads the local
OpenCode database but stores no session id, only token counts, cost and the answer text. So
`results/` contains no account, session or device ids.

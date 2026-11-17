PY ?= python3

.PHONY: all models wire matrix table powered compare xhigh clean

# Everything: advertised metadata, the wire capture, the exploratory matrix, its table.
all: models wire matrix table

# What the gateway advertises per model (context window, effort levels).
models:
	$(PY) scripts/list_models.py --json results/models.json

# What Claude Code puts on the wire for each --effort level (local stub, no key needed).
wire:
	$(PY) scripts/capture_wire.py

# Exploratory run: 2 models x 5 levels x 3 trials. Truncates its output file first.
matrix:
	rm -f results/matrix.jsonl
	$(PY) scripts/effort_matrix.py --trials 3

# Render results/matrix.jsonl as a markdown table.
table:
	$(PY) scripts/summarize.py

# Powered run: low vs max, 10 trials per cell, plus the permutation test.
powered:
	rm -f results/matrix-low-vs-max.jsonl
	$(PY) scripts/effort_matrix.py --efforts low,max --trials 10 \
		--out results/matrix-low-vs-max.jsonl
	$(PY) scripts/summarize.py results/matrix-low-vs-max.jsonl
	$(PY) scripts/compare.py low max results/matrix-low-vs-max.jsonl

# Is xhigh its own level or a synonym for max? pro only.
xhigh:
	rm -f results/matrix-xhigh-vs-max.jsonl
	$(PY) scripts/effort_matrix.py --models deepseek-v4-pro --efforts xhigh,max --trials 10 \
		--out results/matrix-xhigh-vs-max.jsonl
	$(PY) scripts/compare.py xhigh max results/matrix-xhigh-vs-max.jsonl

clean:
	rm -f results/matrix.jsonl results/matrix-low-vs-max.jsonl \
		results/matrix-xhigh-vs-max.jsonl results/wire-format.jsonl results/models.json

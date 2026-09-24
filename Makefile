.PHONY: install run check lint types test evals evals-negative evals-live

install:
	uv sync

run:
	uv run python -m assistant

check: lint types test evals evals-negative

lint:
	uv run ruff check . && uv run ruff format --check .

types:
	uv run mypy

test:
	uv run pytest -q

# The eval gate: every golden conversation must pass with the scripted model.
evals:
	uv run python evals/run_evals.py

# ...and the gate must bite: a model that borrows without searching fails it.
evals-negative:
	@if uv run python evals/run_evals.py --mistakes skip_search >/dev/null; then \
	  echo "eval gate did NOT catch a known-bad model"; exit 1; \
	else echo "eval gate caught the known-bad model: ok"; fi

# Score a real model (set ASSISTANT_PROVIDER, ASSISTANT_MODEL and a key).
evals-live:
	uv run python evals/run_evals.py --threshold 0.8

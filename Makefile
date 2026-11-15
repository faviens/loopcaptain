.DEFAULT_GOAL := help
PORT ?= 8484

help: ## Show this help
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

setup: ## Install dependencies and git hooks
	uv sync
	$(MAKE) hooks

hooks: ## Install the git hooks; commit-msg refuses AI attribution
	uv run pre-commit install --install-hooks

serve: ## The board on http://127.0.0.1:$(PORT), this machine only
	uv run loopcaptain serve --port $(PORT)

demo: ## Free: write the example loop into demo/ (no model, no network); start it from the board
	uv run loopcaptain demo --target demo --no-watch

validate: ## Check a repository's .loops folders: make validate REPO=<path>
	@test -n "$(REPO)" || { echo "usage: make validate REPO=<path>"; exit 2; }
	uv run loopcaptain validate $(REPO)

schema: ## Write the JSON Schema of the protocol to standard/schema/
	uv run loopcaptain schema standard/schema

docs-pages: ## Write the docs pages that come from the code: command line, MCP tools, agents, llms.txt
	uv run python scripts/docs_pages.py

docs: ## Build the documentation site into site/
	uv run --group docs zensical build --clean

docs-serve: ## Preview the documentation site while editing
	uv run --group docs zensical serve

shots: ## Retake the README screenshots from the example loop, light and dark (needs Chrome, cwebp)
	uv run python scripts/shots.py

readme: ## Free: redraw the banner, the how-it-works picture and the architecture picture into docs/assets/
	uv run python scripts/readme_assets.py

release: ## Prepare a release: make release VERSION=x.y.z (bumps, dates the changelog, commits; no tag, no push)
	@test -n "$(VERSION)" || { echo "usage: make release VERSION=x.y.z"; exit 2; }
	uv run python scripts/release.py $(VERSION)

check: ## Format check, lint, types, tests: what CI runs
	uv run ruff format --check .
	uv run ruff check .
	uv run mypy
	uv run pytest -q --cov=loopcaptain --cov-report=term:skip-covered --cov-fail-under=85
	uv run --group docs zensical build --clean

.PHONY: help setup hooks serve demo validate schema docs-pages docs docs-serve shots readme release check

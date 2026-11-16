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

links: ## Check the links inside the built site, offline: every page and anchor it names is there
	uv run python scripts/site_links.py site

docs-serve: ## Preview the documentation site while editing
	uv run --group docs zensical serve

shots: ## Retake the screenshots from invented loops, light and dark (needs Chrome); ONLY=<word> for some
	uv run --with pillow python scripts/shots.py $(ONLY)

readme: ## Free: redraw the banner, the how-it-works picture and the architecture picture into docs/assets/
	uv run python scripts/readme_assets.py

check: ## Format check, lint, types, tests, the site and its links: what CI runs
	uv run ruff format --check .
	uv run ruff check .
	uv run mypy
	uv run pytest -q --cov=loopcaptain --cov-report=term:skip-covered --cov-fail-under=85
	uv run --group docs zensical build --clean
	uv run python scripts/site_links.py site

.PHONY: help setup hooks serve demo validate schema docs-pages docs links docs-serve shots readme check

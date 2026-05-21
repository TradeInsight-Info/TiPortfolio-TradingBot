.PHONY: dev backend frontend down logs test help

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

dev: ## Start backend (detached) + frontend dev server
	docker compose up --build -d
	cd frontend && pnpm dev

backend: ## Start backend with logs attached
	docker compose up --build

frontend: ## Start frontend dev server only
	cd frontend && pnpm install && pnpm dev

down: ## Stop and remove backend containers
	docker compose down

logs: ## Tail backend logs
	docker compose logs -f

test: ## Run backend + frontend tests
	.venv/bin/python -m pytest tests/ -q
	cd frontend && pnpm test

reset-sim: ## Delete simulated rebalance events (requires TIPORTFOLIO_MODE=simulated in .env)
	docker compose exec tradingbot flask sim-reset

reset-all: ## Delete ALL rebalance events and portfolio config (requires TIPORTFOLIO_MODE=simulated in .env)
	docker compose exec tradingbot flask sim-reset --all

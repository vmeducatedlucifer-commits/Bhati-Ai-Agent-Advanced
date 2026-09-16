.PHONY: help install dev backend frontend build sandbox-image test lint clean docker cli-pack

PY := backend/.venv/bin/python
PIP := backend/.venv/bin/pip

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: ## Create the venv and install both stacks
	python3 -m venv backend/.venv
	$(PIP) install -q -r backend/requirements.txt
	cd frontend && npm install
	@test -f backend/.env || cp backend/.env.example backend/.env
	@echo "Ready. Run 'make dev'."

backend: ## Run the API with reload on :8000
	cd backend && .venv/bin/python -m uvicorn app.main:app --reload --port 8000

frontend: ## Run the Vite dev server on :5173
	cd frontend && npm run dev

dev: ## Run both (backend in the background)
	@$(MAKE) -j2 backend frontend

build: ## Build the production frontend bundle
	cd frontend && npm run build

sandbox-image: ## Build the container image each chat's sandbox runs
	docker build -f sandbox/Dockerfile -t rawal-ai-sandbox:latest sandbox

docker: sandbox-image ## Build and run the whole stack with compose
	docker compose up --build

cli-pack: ## Validate the Rawal one-command installer package
	cd cli && npm pack --dry-run

test: ## Run the backend test suite
	cd backend && .venv/bin/python -m pytest -q

lint: ## Typecheck the frontend
	cd frontend && npm run typecheck

clean: ## Remove build output and local data
	rm -rf frontend/dist frontend/node_modules backend/.venv data

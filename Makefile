.PHONY: dev build deploy test train reset inject lint clean help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

dev: ## Start all services locally via docker-compose
	docker-compose up --build

dev-detach: ## Start all services in background
	docker-compose up --build -d

down: ## Stop all services
	docker-compose down

build: ## Build all Docker images
	bash scripts/build-all.sh

deploy: ## Deploy to Kubernetes via Helm
	bash scripts/setup-cluster.sh

test: ## Run all tests
	cd rl-agent && python -m pytest tests/ -v --tb=short

test-unit: ## Run unit tests only (skip destructive/integration)
	cd rl-agent && python -m pytest tests/ -v --tb=short -m "not destructive and not integration"

train: ## Run PPO training loop
	cd rl-agent && python training/train_ppo.py

infer: ## Run baseline inference on all tasks
	cd rl-agent && python inference.py --task all

reset: ## Reset cluster to clean state
	bash scripts/reset-cluster.sh

inject: ## Inject a fault (usage: make inject task=task1)
	bash scripts/inject-fault.sh $(task)

health: ## Run health check on all services
	bash scripts/health-check.sh

lint: ## Lint all Python code
	cd rl-agent && python -m ruff check .
	cd backend/payments-api && python -m ruff check .

clean: ## Remove all containers, volumes, and build artifacts
	docker-compose down -v --remove-orphans
	rm -rf rl-agent/checkpoints/*
	rm -rf rl-agent/__pycache__ rl-agent/**/__pycache__

validate: ## Validate OpenEnv spec compliance
	openenv validate

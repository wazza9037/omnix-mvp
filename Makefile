.PHONY: help install dev run test test-quick cov lint fmt check clean \
       docker-build docker-run docker-stop docker-logs docker-compose-up docker-compose-down

# ── Tunables ──
PY      ?= python3
PORT    ?= 8765
HOST    ?= 0.0.0.0
IMAGE   ?= omnix
TAG     ?= latest

help:
	@echo "OMNIX — common developer tasks"
	@echo ""
	@echo "  Development:"
	@echo "    make install       Install runtime deps"
	@echo "    make dev           Install runtime + dev deps (pytest, ruff)"
	@echo "    make run           Start the OMNIX server on :$(PORT)"
	@echo "    make test          Run the full test suite"
	@echo "    make test-quick    Skip slow tests"
	@echo "    make cov           Run tests with coverage report"
	@echo "    make lint          Run ruff (static analysis)"
	@echo "    make fmt           Run ruff format"
	@echo "    make check         lint + test (useful in pre-commit)"
	@echo "    make clean         Remove __pycache__ / .pytest_cache"
	@echo ""
	@echo "  Docker:"
	@echo "    make docker-build  Build the Docker image"
	@echo "    make docker-run    Run OMNIX in Docker"
	@echo "    make docker-stop   Stop the Docker container"
	@echo "    make docker-logs   Show Docker container logs"
	@echo "    make compose-up    Start with docker-compose (full stack)"
	@echo "    make compose-down  Stop docker-compose stack"
	@echo ""
	@echo "  CI/CD:"
	@echo "    make pre-commit    Install pre-commit hooks"

# ── Development ──

install:
	$(PY) -m pip install -r requirements.txt

dev:
	$(PY) -m pip install -r requirements-dev.txt

run:
	OMNIX_HOST=$(HOST) OMNIX_PORT=$(PORT) $(PY) backend/server_simple.py

test:
	@if $(PY) -c "import pytest" 2>/dev/null; then \
		$(PY) -m pytest; \
	else \
		echo "pytest not installed — falling back to scripts/run_tests.py"; \
		$(PY) scripts/run_tests.py; \
	fi

test-stdlib:
	$(PY) scripts/run_tests.py

test-quick:
	$(PY) -m pytest -m "not slow"

cov:
	$(PY) -m pytest --cov --cov-report=term-missing

lint:
	$(PY) -m ruff check backend

fmt:
	$(PY) -m ruff format backend

check: lint test

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .coverage htmlcov

# ── Docker ──

docker-build:
	docker build -t $(IMAGE):$(TAG) .

docker-run: docker-build
	docker run -d --name omnix \
		-p $(PORT):8765 \
		-p 8766:8766 \
		-v omnix-data:/app/data \
		$(IMAGE):$(TAG)
	@echo "OMNIX running at http://localhost:$(PORT)"

docker-stop:
	docker stop omnix 2>/dev/null || true
	docker rm omnix 2>/dev/null || true

docker-logs:
	docker logs -f omnix

compose-up:
	docker-compose up -d

compose-down:
	docker-compose down

compose-full:
	docker-compose --profile full up -d

# ── CI/CD ──

pre-commit:
	pip install pre-commit
	pre-commit install

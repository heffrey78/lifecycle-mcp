# Makefile for lifecycle-mcp project

.PHONY: help install dev test build-dxt clean lint type-check coverage test-all test-unit test-integration pre-commit viewer tracker-export tracker-restore

help:
	@echo "Available commands:"
	@echo "  make install         - Install the package in production mode"
	@echo "  make dev            - Install the package in development mode with all extras"
	@echo "  make test           - Run all tests with coverage"
	@echo "  make test-unit      - Run unit tests only"
	@echo "  make test-integration - Run integration tests only"
	@echo "  make lint           - Run linting checks"
	@echo "  make type-check     - Run type checking"
	@echo "  make coverage       - Generate coverage report"
	@echo "  make test-all       - Run all quality checks"
	@echo "  make build-dxt      - Build the Desktop Extension (.dxt) package"
	@echo "  make viewer         - Write a read-only HTML view of the tracker to exports/ (DB=path for another)"
	@echo "  make tracker-export - Write lifecycle.db's rows to lifecycle-data.sql, the copy git keeps"
	@echo "  make tracker-restore - Rebuild lifecycle.db from lifecycle-data.sql (INTO=path elsewhere, FORCE=1 to replace)"
	@echo "  make clean          - Clean build artifacts"
	@echo "  make pre-commit     - Install pre-commit hooks"

install:
	pip install .

dev:
	pip install -e ".[all]"
	@echo "Installing pre-commit hooks..."
	pre-commit install

test:
	pytest -n auto --randomly-seed=42

test-unit:
	pytest -m unit -n auto

test-integration:
	pytest -m integration

lint:
	ruff check src tests
	ruff format src tests --check

type-check:
	mypy src tests --strict

coverage:
	pytest --cov=lifecycle_mcp --cov-branch --cov-report=term-missing:skip-covered --cov-report=html --cov-fail-under=90

test-all: lint type-check test
	@echo "All quality checks passed!"

pre-commit:
	pre-commit install
	pre-commit run --all-files

# A read-only HTML snapshot of the tracker. This repository's lifecycle.db unless DB names another; LIFECYCLE_DB is
# deliberately not consulted. The output lands in exports/, which is gitignored.
viewer:
	uv run python scripts/tracker_viewer.py $(if $(DB),--db "$(DB)") $(if $(OUT),--out "$(OUT)")

# The tracker as text in git (REQ-0007-TECH-00). Both use this repository's files, never LIFECYCLE_DB. Restore refuses
# to replace a tracker that holds records unless FORCE=1; stop the server before replacing one it has open.
tracker-export:
	uv run python scripts/tracker_dump.py export

tracker-restore:
	uv run python scripts/tracker_dump.py restore $(if $(INTO),--into "$(INTO)") $(if $(FORCE),--force)

build-dxt:
	@echo "Building Desktop Extension package..."
	python build_dxt.py

clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info
	rm -rf src/*.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name "*.dxt" -delete

# Remove the duplicate lifecycle-mcp-extension directory
remove-duplicate:
	@echo "⚠️  This will remove the lifecycle-mcp-extension directory!"
	@echo "Make sure you've backed up any unique files first."
	@read -p "Continue? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		rm -rf lifecycle-mcp-extension/; \
		echo "✅ Removed lifecycle-mcp-extension directory"; \
	else \
		echo "❌ Cancelled"; \
	fi
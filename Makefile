# Makefile for lifecycle-mcp project

.PHONY: help install dev test build-dxt clean

help:
	@echo "Available commands:"
	@echo "  make install    - Install the package in production mode"
	@echo "  make dev        - Install the package in development mode"
	@echo "  make test       - Run tests"
	@echo "  make build-dxt  - Build the Desktop Extension (.dxt) package"
	@echo "  make clean      - Clean build artifacts"

install:
	pip install .

dev:
	pip install -e .

test:
	python -m pytest tests/

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
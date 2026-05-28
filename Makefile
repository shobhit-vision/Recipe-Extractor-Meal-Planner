.PHONY: help install dev test lint format clean

help:
	@echo "FastAPI Development Commands"
	@echo "=============================="
	@echo "make install    - Install dependencies"
	@echo "make dev        - Run development server"
	@echo "make test       - Run tests"
	@echo "make lint       - Run linting checks"
	@echo "make format     - Format code"
	@echo "make clean      - Clean up generated files"

install:
	pip install -r requirements.txt

dev:
	uvicorn main:app --reload --host 0.0.0.0 --port 8000

test:
	pytest -v

lint:
	ruff check .
	mypy main.py

format:
	black .
	ruff check . --fix

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache
	rm -rf .mypy_cache
	rm -rf htmlcov

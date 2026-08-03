.PHONY: install install-dev test coverage lint format format-check check ci build
install:
	pip install -r requirements.txt
	pip install -e .

install-dev: install
	pip install -r requirements-dev.txt

test:
	python -m pytest -q

coverage:
	python -m pytest --cov --cov-report=term-missing --cov-report=html

lint:
	python -m ruff check .

format:
	python -m ruff format .

format-check:
	python -m ruff format --check .

check: lint format-check test

ci: install-dev lint format-check coverage

build:
	python -m build

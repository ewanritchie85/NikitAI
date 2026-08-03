.PHONY: install test build
install:
	pip install -r requirements.txt
	pip install -e .

test:
	python -m pytest -q

build:
	python -m build

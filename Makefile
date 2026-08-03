.PHONY: install test build
install:
	pip install -r requirements.txt

test:
	python -m pytest -q

build:
	python -m build

.PHONY: setup ingest chat test eval

VENV := .venv
PYTHON := $(VENV)/bin/python

setup:
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install -e .
	npm install

ingest:
	$(PYTHON) -m orbitmesh.ingestion.ingest

chat:
	$(PYTHON) -m orbitmesh.cli.chat

test:
	$(PYTHON) scripts/check_contract.py
	npx promptfoo eval -c promptfoo/smoke.yaml --no-cache

eval:
	npx promptfoo eval -c promptfoo/full.yaml --no-cache

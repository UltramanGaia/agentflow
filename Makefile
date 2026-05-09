.DEFAULT_GOAL := help

.PHONY: help test smoke

PYTHON := $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
help:
	@printf '%s\n' \
	  'Available targets:' \
	  '  test       Run the test suite' \
	  '  smoke      Run the default smoke pipeline'

test:
	$(PYTHON) -m pytest -q

smoke:
	$(PYTHON) -m agentflow run examples/airflow_like.py --output summary

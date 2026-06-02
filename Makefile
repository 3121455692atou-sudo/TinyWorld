.PHONY: install test build dev backend frontend

install:
	uv sync
	npm --prefix frontend install

test:
	uv run pytest

build:
	npm --prefix frontend run build

dev:
	./scripts/dev.sh

backend:
	./scripts/backend.sh

frontend:
	./scripts/frontend.sh


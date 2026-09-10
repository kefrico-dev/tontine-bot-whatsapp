.PHONY: install dev lint format typecheck test check up down logs

install:
	uv sync

dev:
	uv run uvicorn app.main:app --reload

lint:
	uv run ruff check .

format:
	uv run ruff format .

typecheck:
	uv run mypy

test:
	uv run pytest

check: lint typecheck test
	uv run ruff format --check .

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f api

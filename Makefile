.PHONY: install install-lint install-test install-all \
	lint doclint lint-fix format format-check type-check test test-integration test-critical test-with-coverage project-check run run-embedding-service import-dictionary index-rag benchmark-retrieval db-upgrade db-downgrade db-current db-revision

install:
	uv sync

install-lint:
	uv sync --group lint

install-test:
	uv sync --group test

install-all:
	uv sync --all-groups

lint:
	uv run ruff check src
	uv run --group lint pydoclint src

doclint:
	uv run --group lint pydoclint src

lint-fix:
	uv run ruff check src --fix

format:
	uv run ruff format src

format-check:
	uv run ruff format src --check

type-check:
	uv run mypy --config-file mypy.ini src

test:
	uv run pytest -p no:cacheprovider $(ARGS)

test-integration:
	uv run pytest -p no:cacheprovider --integration tests/integration $(ARGS)

test-critical:
	uv run pytest -m critical -q -p no:cacheprovider $(ARGS)

test-with-coverage:
	uv run pytest --cov=src --cov-report=term-missing $(ARGS)

project-check:
	$(MAKE) lint
	$(MAKE) format-check
	$(MAKE) type-check
	$(MAKE) test

run:
	uv run python src/main.py

run-embedding-service:
	uv run python -m embedding_service.main

import-dictionary:
	uv run python src/import_dictionary.py

index-rag:
	uv run python src/index_rag.py

benchmark-retrieval:
	set "DB_HOST=localhost" && set "DB_PORT=5434" && uv run python -m benchmarks.retrieval $(ARGS)

db-upgrade:
	docker compose run --rm --build bot python -m alembic -c alembic.ini upgrade head

db-downgrade:
	docker compose run --rm --build bot python -m alembic -c alembic.ini downgrade -1

db-current:
	docker compose run --rm --build bot python -m alembic -c alembic.ini current

db-revision:
	docker compose run --rm --build bot python -m alembic -c alembic.ini revision $(ARGS)

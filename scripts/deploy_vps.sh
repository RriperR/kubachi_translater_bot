#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_ARGS=(-f docker-compose.yml -f docker-compose.vps-tunnel.yml)

cd "$ROOT_DIR"

echo "[deploy] syncing repository to origin/main"
git fetch origin
git reset --hard origin/main

echo "[deploy] applying migrations"
docker compose "${COMPOSE_ARGS[@]}" run --rm --build bot python -m alembic -c alembic.ini upgrade head

echo "[deploy] rebuilding and starting db + bot"
docker compose "${COMPOSE_ARGS[@]}" up -d --build db bot

echo "[deploy] current status"
docker compose "${COMPOSE_ARGS[@]}" ps

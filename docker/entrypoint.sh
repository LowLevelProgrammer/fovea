#!/usr/bin/env sh
set -eu

cd /app

alembic -c backend/alembic.ini upgrade head

exec "$@"


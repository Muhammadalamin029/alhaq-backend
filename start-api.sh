#!/bin/sh
set -e

echo "========================================"
echo "LEL Store API starting..."
echo "========================================"

echo "Running database migrations..."
# "heads" (plural): the repo has multiple migration heads, "head" would abort
# with "Multiple head revisions are present".
alembic upgrade heads

echo "Database migrations completed."

echo "Starting FastAPI..."
exec uvicorn main:app --host 0.0.0.0 --port 8000

#!/bin/sh
set -e

echo "========================================"
echo "LEL Store API starting..."
echo "========================================"

echo "Running database migrations..."
alembic upgrade head

echo "Database migrations completed."

echo "Starting FastAPI..."
exec uvicorn main:app --host 0.0.0.0 --port 8000

#!/bin/bash

# Single command to start FastAPI and Celery for both development and production
# Usage: ./start.sh dev    # Development mode
#        ./start.sh prod   # Production mode

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if environment argument is provided
if [ $# -ne 1 ]; then
    echo "Usage: $0 [dev|prod]"
    echo "  dev  - Development mode (uvicorn + celery with reload)"
    echo "  prod - Production mode (gunicorn + celery)"
    exit 1
fi

ENV=$1

if [ "$ENV" != "dev" ] && [ "$ENV" != "prod" ]; then
    print_error "Invalid environment. Use 'dev' or 'prod'"
    exit 1
fi

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Check if virtual environment exists
if [ ! -d "$SCRIPT_DIR/.venv" ]; then
    print_error "Virtual environment not found. Please create it first:"
    print_error "python3 -m venv .venv"
    print_error "source .venv/bin/activate"
    print_error "pip install -r requirements.txt"
    exit 1
fi

# Function to cleanup processes on exit
cleanup() {
    print_warning "Stopping all services..."
    if [ ! -z "$CELERY_PID" ]; then
        kill $CELERY_PID 2>/dev/null || true
    fi
    if [ ! -z "$FASTAPI_PID" ]; then
        kill $FASTAPI_PID 2>/dev/null || true
    fi
    print_success "All services stopped!"
    exit 0
}

# Set up signal handlers
trap cleanup SIGINT SIGTERM

# Start Celery worker
print_status "Starting Celery worker ($ENV mode)..."
cd "$SCRIPT_DIR"

if [ "$ENV" = "prod" ]; then
    .venv/bin/celery -A core.celery_app worker --loglevel=info --concurrency=4 --queues=default,emails,notifications &
else
    .venv/bin/celery -A core.celery_app worker --loglevel=info --concurrency=2 --queues=default,emails,notifications &
fi

CELERY_PID=$!

# Wait a moment for Celery to start
sleep 2

# Start FastAPI server
print_status "Starting FastAPI server ($ENV mode)..."

if [ "$ENV" = "prod" ]; then
    .venv/bin/gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000 --access-logfile - --error-logfile - &
else
    .venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --reload &
fi

FASTAPI_PID=$!

# Wait a moment for FastAPI to start
sleep 3

print_success "Both services started in $ENV mode!"
echo ""
print_status "🌐 FastAPI: http://localhost:8000"
print_status "📚 API Docs: http://localhost:8000/docs"
print_status "🔄 Celery: Running in background"
echo ""
print_warning "Press Ctrl+C to stop all services..."

# Wait for processes
wait
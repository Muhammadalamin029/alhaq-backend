#!/bin/bash

# Standalone Celery worker startup script
# Usage: ./start_celery.sh [concurrency]

set -e

# Default concurrency
CONCURRENCY=${1:-1}

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}============================================================${NC}"
echo -e "${BLUE}🔄 CELERY WORKER STARTUP${NC}"
echo -e "${BLUE}============================================================${NC}"
echo -e "Concurrency: ${YELLOW}${CONCURRENCY}${NC}"
echo -e "Memory Optimized: ${YELLOW}$([ $CONCURRENCY -eq 1 ] && echo "Yes" || echo "No")${NC}"
echo -e "Queues: ${YELLOW}default, emails, notifications${NC}"
echo -e "${BLUE}============================================================${NC}"

# Check if uv exists
if command -v uv &> /dev/null; then
    echo -e "${GREEN}✅ Using uv to run Celery${NC}"
    CELERY_CMD="uv run celery"
elif [ -f ".venv/bin/celery" ]; then
    echo -e "${GREEN}✅ Using virtual environment Celery${NC}"
    CELERY_CMD=".venv/bin/celery"
elif command -v celery &> /dev/null; then
    echo -e "${GREEN}✅ Using system Celery${NC}"
    CELERY_CMD="celery"
else
    echo -e "${RED}❌ Celery not found. Please install Celery or activate virtual environment${NC}"
    exit 1
fi

# Build command
CMD="$CELERY_CMD -A core.celery_app worker --loglevel=info --concurrency=$CONCURRENCY --queues=default,emails,notifications"

echo -e "${BLUE}🚀 Starting Celery worker...${NC}"
echo -e "Command: ${YELLOW}$CMD${NC}"
echo ""

# Handle Ctrl+C gracefully
trap 'echo -e "\n${YELLOW}🛑 Stopping Celery worker...${NC}"; kill $CELERY_PID 2>/dev/null; wait $CELERY_PID 2>/dev/null; echo -e "${GREEN}✅ Celery worker stopped${NC}"; exit 0' INT TERM

# Start Celery worker
eval $CMD &
CELERY_PID=$!

# Wait for Celery process
wait $CELERY_PID

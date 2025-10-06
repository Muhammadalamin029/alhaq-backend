#!/usr/bin/env python3
"""
Single command to start FastAPI and Celery for both development and production
Usage:
    python3 start_app.py dev    # Development mode
    python3 start_app.py prod   # Production mode
"""

import os
import sys
import subprocess
import signal
import time
from pathlib import Path

def start_celery(env="dev"):
    """Start Celery worker"""
    # Use virtual environment celery
    celery_cmd = ".venv/bin/celery"
    
    if env == "prod":
        # Production: Use gunicorn for FastAPI and celery for worker
        cmd = [
            celery_cmd, "-A", "core.celery_app", "worker",
            "--loglevel=info",
            "--concurrency=4",
            "--queues=default,emails,notifications"
        ]
    else:
        # Development: Use uvicorn for FastAPI and celery for worker
        cmd = [
            celery_cmd, "-A", "core.celery_app", "worker",
            "--loglevel=info",
            "--concurrency=2",
            "--queues=default,emails,notifications"
        ]
    
    print(f"🚀 Starting Celery worker ({env} mode)...")
    return subprocess.Popen(cmd)

def start_fastapi(env="dev"):
    """Start FastAPI server"""
    # Use virtual environment python
    python_cmd = ".venv/bin/python"
    
    if env == "prod":
        # Production: Use gunicorn with uvicorn workers
        cmd = [
            ".venv/bin/gunicorn", "main:app",
            "-w", "4",
            "-k", "uvicorn.workers.UvicornWorker",
            "--bind", "0.0.0.0:8000",
            "--access-logfile", "-",
            "--error-logfile", "-"
        ]
    else:
        # Development: Use uvicorn directly
        cmd = [
            ".venv/bin/uvicorn", "main:app",
            "--host", "0.0.0.0",
            "--port", "8000",
            "--reload"
        ]
    
    print(f"🚀 Starting FastAPI server ({env} mode)...")
    return subprocess.Popen(cmd)

def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ["dev", "prod"]:
        print("Usage: python3 start_app.py [dev|prod]")
        print("  dev  - Development mode (uvicorn + celery with reload)")
        print("  prod - Production mode (gunicorn + celery)")
        sys.exit(1)
    
    env = sys.argv[1]
    processes = []
    
    try:
        # Start Celery worker
        celery_proc = start_celery(env)
        processes.append(celery_proc)
        
        # Wait a moment for Celery to start
        time.sleep(2)
        
        # Start FastAPI server
        fastapi_proc = start_fastapi(env)
        processes.append(fastapi_proc)
        
        print(f"\n✅ Both services started in {env} mode!")
        print("🌐 FastAPI: http://localhost:8000")
        print("📚 API Docs: http://localhost:8000/docs")
        print("🔄 Celery: Running in background")
        print("\nPress Ctrl+C to stop all services...")
        
        # Wait for processes
        for proc in processes:
            proc.wait()
            
    except KeyboardInterrupt:
        print("\n🛑 Stopping all services...")
        for proc in processes:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        print("✅ All services stopped!")

if __name__ == "__main__":
    main()
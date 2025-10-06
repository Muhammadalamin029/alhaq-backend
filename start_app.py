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
    # Check if we're in a virtual environment or using uv
    if os.path.exists(".venv/bin/celery"):
        celery_cmd = ".venv/bin/celery"
        celery_args = []
    elif os.path.exists("uv"):
        celery_cmd = "uv"
        celery_args = ["run", "celery"]
    else:
        celery_cmd = "celery"
        celery_args = []
    
    if env == "prod":
        # Production: Use gunicorn for FastAPI and celery for worker
        cmd = [celery_cmd] + celery_args + [
            "-A", "core.celery_app", "worker",
            "--loglevel=info",
            "--concurrency=4",
            "--queues=default,emails,notifications"
        ]
    else:
        # Development: Use uvicorn for FastAPI and celery for worker
        cmd = [celery_cmd] + celery_args + [
            "-A", "core.celery_app", "worker",
            "--loglevel=info",
            "--concurrency=2",
            "--queues=default,emails,notifications"
        ]
    
    print(f"🚀 Starting Celery worker ({env} mode)...")
    return subprocess.Popen(cmd)

def start_fastapi(env="dev", memory_optimized=False):
    """Start FastAPI server"""
    # Check if we're in a virtual environment or using uv
    if os.path.exists(".venv/bin/uvicorn"):
        # Local development with virtual environment
        if env == "prod":
            workers = "1" if memory_optimized else "4"
            cmd = [
                ".venv/bin/uvicorn", "main:app",
                "--host", "0.0.0.0",
                "--port", "8000",
                "--workers", workers
            ]
        else:
            cmd = [
                ".venv/bin/uvicorn", "main:app",
                "--host", "0.0.0.0",
                "--port", "8000",
                "--reload"
            ]
    elif os.path.exists("uv"):
        # Production with uv
        if env == "prod":
            workers = "1" if memory_optimized else "4"
            cmd = [
                "uv", "run", "uvicorn", "main:app",
                "--host", "0.0.0.0",
                "--port", "8000",
                "--workers", workers
            ]
        else:
            cmd = [
                "uv", "run", "uvicorn", "main:app",
                "--host", "0.0.0.0",
                "--port", "8000",
                "--reload"
            ]
    else:
        # Fallback to system commands
        if env == "prod":
            workers = "1" if memory_optimized else "4"
            cmd = [
                "uvicorn", "main:app",
                "--host", "0.0.0.0",
                "--port", "8000",
                "--workers", workers
            ]
        else:
            cmd = [
                "uvicorn", "main:app",
                "--host", "0.0.0.0",
                "--port", "8000",
                "--reload"
            ]
    
    mode_text = f"{env} mode" + (" (memory-optimized)" if memory_optimized else "")
    print(f"🚀 Starting FastAPI server ({mode_text})...")
    return subprocess.Popen(cmd)

def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ["dev", "prod", "prod-memory"]:
        print("Usage: python3 start_app.py [dev|prod|prod-memory]")
        print("  dev         - Development mode (uvicorn + celery with reload)")
        print("  prod        - Production mode (uvicorn + celery, 4 workers)")
        print("  prod-memory - Memory-optimized production (1 worker each)")
        sys.exit(1)
    
    env = sys.argv[1]
    memory_optimized = env == "prod-memory"
    if memory_optimized:
        env = "prod"  # Use prod settings but with memory optimization
    
    processes = []
    
    try:
        # Start Celery worker (with error handling)
        celery_proc = None
        try:
            celery_proc = start_celery(env)
            processes.append(celery_proc)
            print("✅ Celery worker started successfully!")
        except Exception as e:
            print(f"⚠️  Warning: Failed to start Celery worker: {e}")
            print("   Continuing with FastAPI only...")
            celery_proc = None
        
        # Wait a moment for Celery to start (if it started)
        if celery_proc:
            time.sleep(2)
        
        # Start FastAPI server
        fastapi_proc = start_fastapi(env, memory_optimized)
        processes.append(fastapi_proc)
        
        if celery_proc:
            mode_text = f"{env} mode" + (" (memory-optimized)" if memory_optimized else "")
            print(f"\n✅ Both services started in {mode_text}!")
            print("🔄 Celery: Running in background")
        else:
            mode_text = f"{env} mode" + (" (memory-optimized)" if memory_optimized else "")
            print(f"\n✅ FastAPI started in {mode_text}! (Celery unavailable)")
        print("🌐 FastAPI: http://localhost:8000")
        print("📚 API Docs: http://localhost:8000/docs")
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
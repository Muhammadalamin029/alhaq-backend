#!/usr/bin/env python3
"""
Simple production startup script for Render deployment
Only starts FastAPI, no Celery worker
"""

import os
import subprocess
import sys

def start_fastapi():
    """Start FastAPI server only"""
    # Check if we're using uv
    if os.path.exists("uv"):
        cmd = [
            "uv", "run", "uvicorn", "main:app",
            "--host", "0.0.0.0",
            "--port", "8000",
            "--workers", "4"
        ]
    else:
        # Fallback to system commands
        cmd = [
            "uvicorn", "main:app",
            "--host", "0.0.0.0",
            "--port", "8000",
            "--workers", "4"
        ]
    
    print("🚀 Starting FastAPI server (production mode)...")
    print(f"Command: {' '.join(cmd)}")
    
    # Start the process
    process = subprocess.Popen(cmd)
    
    try:
        # Wait for the process
        process.wait()
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
        process.terminate()
        process.wait()

if __name__ == "__main__":
    start_fastapi()

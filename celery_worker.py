#!/usr/bin/env python3
"""
Script to start Celery worker with proper configuration
"""

import os
import sys
import subprocess
from pathlib import Path

def start_celery_worker():
    """Start Celery worker with recommended settings"""
    
    # Change to project directory
    project_dir = Path(__file__).parent
    os.chdir(project_dir)
    
    print("🚀 Starting Celery Worker for Email & Notification Processing...")
    print(f"📁 Working directory: {project_dir}")
    print("=" * 50)
    
    # Celery worker command
    cmd = [
        ".venv/bin/celery",
        "-A", "core.celery_app",
        "worker",
        "--loglevel=info",
        "--concurrency=2",
        "--queues=default,emails,notifications",
        "--prefetch-multiplier=1"
    ]
    
    print(f"📋 Command: {' '.join(cmd)}")
    print("=" * 50)
    print("📧 The worker will process email and notification tasks from the queue")
    print("🔄 Press Ctrl+C to stop the worker")
    print("=" * 50)
    
    try:
        # Start the Celery worker
        subprocess.run(cmd, check=True)
    except KeyboardInterrupt:
        print("\n⏹️  Celery worker stopped by user")
    except subprocess.CalledProcessError as e:
        print(f"❌ Celery worker failed to start: {e}")
        print("\n💡 Troubleshooting:")
        print("   - Make sure you're in the project directory")
        print("   - Check if Redis is running: redis-cli ping")
        print("   - Verify virtual environment is activated")
        sys.exit(1)
    except FileNotFoundError:
        print("❌ Celery not found. Make sure it's installed in the virtual environment")
        print("💡 Install with: .venv/bin/pip install celery")
        sys.exit(1)

if __name__ == "__main__":
    start_celery_worker()
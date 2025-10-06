#!/usr/bin/env python3
"""
Standalone Celery worker startup script
Run this separately from FastAPI for better resource management
"""

import os
import subprocess
import sys
import time
import signal

def start_celery_worker(concurrency=1, memory_optimized=True):
    """Start Celery worker with configurable concurrency"""
    
    # Check if we're using uv
    if os.path.exists("uv"):
        cmd = [
            "uv", "run", "celery", "-A", "core.celery_app", "worker",
            "--loglevel=info",
            "--concurrency", str(concurrency),
            "--queues=default,emails,notifications"
        ]
    elif os.path.exists(".venv/bin/celery"):
        cmd = [
            ".venv/bin/celery", "-A", "core.celery_app", "worker",
            "--loglevel=info",
            "--concurrency", str(concurrency),
            "--queues=default,emails,notifications"
        ]
    else:
        # Fallback to system commands
        cmd = [
            "celery", "-A", "core.celery_app", "worker",
            "--loglevel=info",
            "--concurrency", str(concurrency),
            "--queues=default,emails,notifications"
        ]
    
    mode_text = f"concurrency={concurrency}" + (" (memory-optimized)" if memory_optimized else "")
    print(f"🚀 Starting Celery worker ({mode_text})...")
    print(f"Command: {' '.join(cmd)}")
    
    # Start the process
    process = subprocess.Popen(cmd)
    
    # Handle graceful shutdown
    def signal_handler(sig, frame):
        print(f"\n🛑 Received signal {sig}, shutting down Celery worker...")
        process.terminate()
        try:
            process.wait(timeout=10)
            print("✅ Celery worker stopped gracefully")
        except subprocess.TimeoutExpired:
            print("⚠️  Force killing Celery worker...")
            process.kill()
            process.wait()
            print("✅ Celery worker force stopped")
        sys.exit(0)
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # Wait for the process
        return_code = process.wait()
        print(f"Celery worker exited with code: {return_code}")
        return return_code
    except Exception as e:
        print(f"❌ Error running Celery worker: {e}")
        return 1

def main():
    """Main function with different concurrency options"""
    if len(sys.argv) < 2:
        print("Usage: python3 start_celery_only.py [concurrency]")
        print("  concurrency - Number of worker processes (default: 1)")
        print("")
        print("Examples:")
        print("  python3 start_celery_only.py 1    # Single process (memory-optimized)")
        print("  python3 start_celery_only.py 2    # Two processes")
        print("  python3 start_celery_only.py 4    # Four processes (standard)")
        print("")
        print("For Render deployment, use: python3 start_celery_only.py 1")
        sys.exit(1)
    
    try:
        concurrency = int(sys.argv[1])
        if concurrency < 1:
            print("❌ Concurrency must be at least 1")
            sys.exit(1)
    except ValueError:
        print("❌ Concurrency must be a number")
        sys.exit(1)
    
    memory_optimized = concurrency == 1
    
    print("=" * 60)
    print("🔄 CELERY WORKER STARTUP")
    print("=" * 60)
    print(f"Concurrency: {concurrency}")
    print(f"Memory Optimized: {memory_optimized}")
    print(f"Queues: default, emails, notifications")
    print("=" * 60)
    
    # Start Celery worker
    exit_code = start_celery_worker(concurrency, memory_optimized)
    sys.exit(exit_code)

if __name__ == "__main__":
    main()

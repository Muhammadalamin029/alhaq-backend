#!/usr/bin/env python3
"""
Celery worker entry point

This module provides the entry point for running Celery workers.
It handles importing all necessary modules and configurations.

Usage:
    # Run worker with default concurrency
    celery -A celery_worker worker --loglevel=info
    
    # Run worker with specific concurrency
    celery -A celery_worker worker --loglevel=info --concurrency=4
    
    # Run worker with specific queues
    celery -A celery_worker worker --loglevel=info --queues=emails,default
    
    # Run flower for monitoring (optional)
    celery -A celery_worker flower
"""

import logging
import os

try:
    # Use the application's logging configuration
    from core.logging_config import setup_logging, get_logger
    setup_logging(log_level="INFO")
    logger = get_logger("celery_worker")
except ImportError:
    # Fallback to basic logging if app logging is not available
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger(__name__)

try:
    # Import the celery app
    from core.celery_app import celery_app
    
    # Import all task modules to ensure they're registered
    from core import tasks
    
    logger.info("Celery worker starting...")
    logger.info(f"Registered tasks: {list(celery_app.tasks.keys())}")
    
except ImportError as e:
    logger.error(f"Failed to import celery app or tasks: {e}")

# Export the celery app for the celery command
app = celery_app

if __name__ == '__main__':
    """
    This allows running the worker directly with:
    python celery_worker.py
    """
    celery_app.worker_main()
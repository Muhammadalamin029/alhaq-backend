from celery import Celery
from core.config import settings

# Create Celery app instance
celery_app = Celery(
    "alhaq_backend",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["core.tasks"]  # Import tasks module
)

# Celery configuration
celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    
    # Task execution settings
    task_always_eager=False,  # Set to True for testing without worker
    task_eager_propagates=True,
    
    # Worker settings
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
    
    # Result backend settings
    result_expires=3600,  # 1 hour
    
    # Task routing (optional - can route different tasks to different queues)
    task_routes={
        'core.tasks.send_verification_email': {'queue': 'emails'},
        'core.tasks.send_password_reset_email': {'queue': 'emails'},
    },
    
    # Default queue
    task_default_queue='default',
    
    # Retry settings
    task_annotations={
        'core.tasks.send_verification_email': {
            'rate_limit': '10/m',  # 10 tasks per minute
            'retry_policy': {
                'max_retries': 3,
                'interval_start': 0,
                'interval_step': 0.2,
                'interval_max': 0.2,
            }
        },
        'core.tasks.send_password_reset_email': {
            'rate_limit': '10/m',
            'retry_policy': {
                'max_retries': 3,
                'interval_start': 0,
                'interval_step': 0.2,
                'interval_max': 0.2,
            }
        }
    }
)

# Auto-discover tasks
celery_app.autodiscover_tasks(['core'])
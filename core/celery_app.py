from celery import Celery
from core.config import settings
import ssl

# Configure Redis connection based on URL scheme
def get_redis_config():
    broker_url = settings.CELERY_BROKER_URL
    backend_url = settings.CELERY_RESULT_BACKEND
    
    # Check if using SSL (rediss://)
    if broker_url.startswith('rediss://'):
        return {
            'broker_url': broker_url,
            'result_backend': backend_url,
            'broker_use_ssl': {
                'ssl_cert_reqs': ssl.CERT_REQUIRED,
                'ssl_ca_certs': None,
                'ssl_certfile': None,
                'ssl_keyfile': None,
            },
            'redis_backend_use_ssl': {
                'ssl_cert_reqs': ssl.CERT_REQUIRED,
                'ssl_ca_certs': None,
                'ssl_certfile': None,
                'ssl_keyfile': None,
            }
        }
    else:
        return {
            'broker_url': broker_url,
            'result_backend': backend_url,
        }

redis_config = get_redis_config()

celery_app = Celery(
    "alhaq_backend",
    broker=redis_config['broker_url'],
    backend=redis_config['result_backend'],
    include=["core.tasks"]
)

# Update configuration
config_updates = {
    "task_serializer": "json",
    "accept_content": ["json"],
    "result_serializer": "json",
    "timezone": "UTC",
    "enable_utc": True,
    "task_always_eager": False,
    "task_eager_propagates": True,
    "worker_prefetch_multiplier": 1,
    "worker_max_tasks_per_child": 1000,
    "result_expires": 3600,
    "task_routes": {
        "core.tasks.send_verification_email": {"queue": "emails"},
        "core.tasks.send_password_reset_email": {"queue": "emails"},
        "core.tasks.send_notification_email": {"queue": "emails"},
        "core.tasks.send_notification": {"queue": "notifications"},
    },
    "task_default_queue": "default",
    "task_annotations": {
        "core.tasks.send_verification_email": {
            "rate_limit": "10/m",
            "retry_policy": {"max_retries": 3, "interval_start": 0, "interval_step": 0.2, "interval_max": 0.2},
        },
        "core.tasks.send_password_reset_email": {
            "rate_limit": "10/m",
            "retry_policy": {"max_retries": 3, "interval_start": 0, "interval_step": 0.2, "interval_max": 0.2},
        },
        "core.tasks.send_notification_email": {
            "rate_limit": "20/m",
            "retry_policy": {"max_retries": 3, "interval_start": 0, "interval_step": 0.2, "interval_max": 0.2},
        },
        "core.tasks.send_notification": {
            "rate_limit": "50/m",
            "retry_policy": {"max_retries": 3, "interval_start": 0, "interval_step": 0.2, "interval_max": 0.2},
        },
    },
}

# Add SSL configuration if using rediss://
if 'broker_use_ssl' in redis_config:
    config_updates.update({
        'broker_use_ssl': redis_config['broker_use_ssl'],
        'redis_backend_use_ssl': redis_config['redis_backend_use_ssl'],
    })

celery_app.conf.update(config_updates)

celery_app.autodiscover_tasks(["core"], force=True)

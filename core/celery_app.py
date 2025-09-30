from celery import Celery
from core.config import settings

celery_app = Celery(
    "alhaq_backend",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["core.tasks"]
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,

    task_always_eager=False,
    task_eager_propagates=True,

    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
    result_expires=3600,

    task_routes={
        "core.tasks.send_verification_email": {"queue": "emails"},
        "core.tasks.send_password_reset_email": {"queue": "emails"},
    },
    task_default_queue="default",
    task_annotations={
        "core.tasks.send_verification_email": {
            "rate_limit": "10/m",
            "retry_policy": {"max_retries": 3, "interval_start": 0, "interval_step": 0.2, "interval_max": 0.2},
        },
        "core.tasks.send_password_reset_email": {
            "rate_limit": "10/m",
            "retry_policy": {"max_retries": 3, "interval_start": 0, "interval_step": 0.2, "interval_max": 0.2},
        },
    },
)

# Required for rediss:// on Railway/Upstash/etc.
celery_app.conf.broker_use_ssl = {"ssl_cert_reqs": "CERT_NONE"}
celery_app.conf.redis_backend_use_ssl = {"ssl_cert_reqs": "CERT_NONE"}

celery_app.autodiscover_tasks(["core"], force=True)

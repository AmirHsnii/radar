"""
Celery application — broker + backend both on Redis.

Import this module wherever you need the celery_app instance.
Tasks are auto-discovered from the `include` list.
"""
from celery import Celery
from app.core.settings_env import REDIS_URL

celery_app = Celery(
    "bitpin_radar",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=[
        "app.tasks.crawl_task",
        "app.tasks.process_task",
        "app.tasks.publish_task",
    ],
)

celery_app.conf.update(
    # Serialisation
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],

    # Timezone
    timezone="Asia/Tehran",
    enable_utc=True,

    # Reliability
    task_acks_late=True,           # ack only after the task completes
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,   # one task at a time per worker process
    task_track_started=True,

    # Result TTL — keep for 24 h, then discard
    result_expires=86400,

    # Memory safety — restart worker after N tasks to prevent leaks
    worker_max_tasks_per_child=200,
)

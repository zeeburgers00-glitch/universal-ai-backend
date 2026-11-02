import os
from celery import Celery

BROKER = os.getenv("CELERY_BROKER_URL", "").strip()
if not BROKER:
    raise RuntimeError("CELERY_BROKER_URL is required for the durable autopilot worker")

celery_app = Celery("autopilot_worker", broker=BROKER, backend=BROKER, include=["autopilot_worker.tasks"])
celery_app.conf.update(
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    result_expires=86400,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    broker_connection_retry_on_startup=True,
)

"""Celery task publisher for durable chat orchestration."""
import os
from celery import Celery


def enqueue_chat(payload: dict) -> None:
    broker = os.getenv("CELERY_BROKER_URL", "").strip()
    if not broker:
        raise RuntimeError("CELERY_BROKER_URL is not configured")
    celery_app = Celery("autopilot_api", broker=broker)
    celery_app.send_task("autopilot_worker.run_chat", kwargs={"payload": payload}, task_id=payload["task_id"])

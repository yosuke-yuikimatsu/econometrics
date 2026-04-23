from __future__ import annotations

from celery import Celery
from kombu import Queue

from app.config import settings
from app.logging_utils import configure_logging

configure_logging()

celery_app = Celery("cbr_parser")
celery_app.conf.update(
    broker_url=settings.broker_url,
    result_backend=settings.result_backend,

    task_default_exchange="cbr",
    task_default_exchange_type="direct",
    task_default_routing_key="default",

    task_acks_late=settings.celery_task_acks_late,
    worker_prefetch_multiplier=settings.celery_prefetch_multiplier,
    task_reject_on_worker_lost=True,
    task_track_started=True,

    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],

    task_default_retry_delay=5,
    broker_connection_retry_on_startup=True,

    task_queues=(
        Queue("bootstrap", routing_key="bootstrap"),
        Queue("fetch", routing_key="fetch"),
        Queue("parse", routing_key="parse"),
        Queue("aggregate", routing_key="aggregate"),
    ),

    task_routes={
        "app.tasks.bootstrap.*": {"queue": "bootstrap", "routing_key": "bootstrap"},
        "app.tasks.fetch.*": {"queue": "fetch", "routing_key": "fetch"},
        "app.tasks.parse.*": {"queue": "parse", "routing_key": "parse"},
        "app.tasks.aggregate.*": {"queue": "aggregate", "routing_key": "aggregate"},
    },

    imports=(
        "app.tasks.bootstrap",
        "app.tasks.fetch",
        "app.tasks.parse",
        "app.tasks.aggregate",
    ),
)

celery_app.set_default()
celery_app.set_current()
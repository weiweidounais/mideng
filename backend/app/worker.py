"""Production worker: uv run celery -A app.worker.celery_app worker --concurrency=2."""
from celery import Celery
from .config import config
from .db import init_db

celery_app=Celery("zhixu",broker=config.redis_url,backend=config.redis_url)
celery_app.conf.update(task_acks_late=True,task_reject_on_worker_lost=True,worker_prefetch_multiplier=1,
                       task_track_started=True,broker_connection_retry_on_startup=True,
                       result_expires=86400,task_soft_time_limit=7800,task_time_limit=8000)

@celery_app.task(name="knowledge.process")
def process(task_id):
    init_db()
    from .ingestion import process_task
    process_task(task_id)

"""Celery application configuration for async task processing."""

from celery import Celery
from celery.schedules import crontab

from config.settings import get_settings

settings = get_settings()

celery_app = Celery(
    "housinghand",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

# Auto-discover tasks in the tasks package
celery_app.autodiscover_tasks(["src.tasks"])

# Periodic task schedule
celery_app.conf.beat_schedule = {
    "update-predictions-daily": {
        "task": "src.tasks.update_predictions.update_all_predictions",
        "schedule": crontab(hour=2, minute=0),  # 2:00 AM UTC
    },
    "calculate-benchmarks-weekly": {
        "task": "src.tasks.calculate_benchmarks.recalculate_all_benchmarks",
        "schedule": crontab(hour=3, minute=0, day_of_week="sunday"),
    },
    "health-checks-hourly": {
        "task": "src.tasks.health_checks.run_health_checks",
        "schedule": crontab(minute=0),  # Every hour
    },
    "generate-alerts-daily": {
        "task": "src.tasks.alert_generation.generate_daily_alerts",
        "schedule": crontab(hour=8, minute=0),  # 8:00 AM UTC
    },
}

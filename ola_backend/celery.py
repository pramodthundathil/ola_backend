# ola_backend/celery.py
import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ola_backend.settings')

app = Celery('ola_backend')

# Load settings from Django settings.py with CELERY_ prefix
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks from all installed apps
app.autodiscover_tasks()

# Optional: Celery Beat schedule for periodic tasks
app.conf.beat_schedule = {
    "send_emi_reminders_daily": {
        "task": "finance.tasks.send_emi_reminders",  
        "schedule": crontab(hour=6, minute=0),      
    },
}
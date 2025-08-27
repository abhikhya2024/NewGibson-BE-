import os
from celery import Celery

# Set default Django settings
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "myproject.settings")

app = Celery("myproject")

# Load settings with "CELERY_" prefix from settings.py
app.config_from_object("django.conf:settings", namespace="CELERY")

# Auto-discover tasks.py inside installed apps
app.autodiscover_tasks()

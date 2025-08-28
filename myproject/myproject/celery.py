import os
from celery import Celery
import logging.config
from django.conf import settings

# Set default Django settings
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "myproject.settings")

app = Celery("myproject")

# Load settings with "CELERY_" prefix
app.config_from_object("django.conf:settings", namespace="CELERY")

# Auto-discover tasks
app.autodiscover_tasks()

# Load Django logging into Celery worker
logging.config.dictConfig(settings.LOGGING)

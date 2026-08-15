from celery import Celery

from app.core.runtime import get_env


celery_app = Celery("zhifeng-image", broker=get_env("RABBITMQ_URL", "amqp://guest:guest@localhost:5672//"))


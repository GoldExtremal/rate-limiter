import os
import uuid

NGINX_URL = os.environ.get("NGINX_URL", "http://localhost:8080")
APP_URLS = os.environ.get("APP_URLS", "http://localhost:8001,http://localhost:8002").split(",")
DEFAULT_LIMIT = 100


def unique_client_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"

from app.config import Settings
from tests.conftest import running_client


async def test_app_starts_and_serves_health_without_redis() -> None:
    settings = Settings(redis_url="redis://127.0.0.1:1/0", instance_id="no-redis")
    async for client in running_client(settings):
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.headers["X-Instance-Id"] == "no-redis"


async def test_app_starts_with_redis(test_redis_url: str) -> None:
    settings = Settings(redis_url=test_redis_url, instance_id="with-redis")
    async for client in running_client(settings):
        response = await client.get("/health")
        assert response.status_code == 200

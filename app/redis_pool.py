import asyncio
import logging

from redis.asyncio import ConnectionPool, Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.config import Settings

logger = logging.getLogger(__name__)


def create_redis_pool(settings: Settings) -> ConnectionPool:
    return ConnectionPool.from_url(
        settings.redis_url,
        max_connections=settings.redis_max_connections,
        socket_timeout=settings.redis_timeout_sec,
        socket_connect_timeout=settings.redis_timeout_sec,
        retry_on_timeout=False,
        health_check_interval=30,
    )


async def warm_up_redis(redis: Redis, timeout_sec: float) -> bool:
    try:
        async with asyncio.timeout(timeout_sec):
            await redis.ping()
    except (RedisConnectionError, RedisTimeoutError, TimeoutError, OSError) as error:
        logger.warning("redis is unavailable on startup: %s", type(error).__name__)
        return False
    return True

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis

from app.admission import Admission
from app.api import router
from app.config import Settings
from app.instance import InstanceIdASGI
from app.limiter import RateLimiter
from app.redis_pool import create_redis_pool, warm_up_redis


def configure_logging(settings: Settings) -> None:
    logging.basicConfig(
        level=settings.log_level.upper(),
        format=f"%(asctime)s %(levelname)s instance={settings.instance_id} %(name)s %(message)s",
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        pool = create_redis_pool(app_settings)
        redis = Redis(connection_pool=pool)
        await warm_up_redis(redis, app_settings.redis_timeout_sec)
        app.state.limiter = RateLimiter(
            redis,
            Admission(app_settings.redis_max_connections),
            default_limit=app_settings.rate_limit,
            window_sec=app_settings.window_sec,
        )
        try:
            yield
        finally:
            await redis.aclose()
            await pool.aclose()

    app = FastAPI(title="Rate Limiter", lifespan=lifespan)
    app.state.settings = app_settings
    app.include_router(router)
    return app


def build_asgi_app() -> InstanceIdASGI:
    settings = Settings()
    configure_logging(settings)
    return InstanceIdASGI(create_app(settings), settings.instance_id)

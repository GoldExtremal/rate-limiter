import socket
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    redis_url: str = "redis://redis:6379/0"
    database_url: str = "postgresql://ratelimiter:local-dev-only@postgres:5432/ratelimiter"
    limits_query_timeout_ms: int = Field(default=1000, gt=0)
    limits_refresh_sec: float = Field(default=10, gt=0)
    rate_limit: int = Field(default=100, ge=0)
    window_sec: int = Field(default=60, gt=0)
    fail_mode_open: bool = True
    redis_timeout_ms: int = Field(default=500, gt=0)
    redis_max_connections: int = Field(default=64, gt=0)
    redis_queue_timeout_ms: int = Field(default=1000, gt=0)
    breaker_failure_threshold: int = Field(default=5, gt=0)
    breaker_cooldown_sec: float = Field(default=5, gt=0)
    breaker_window_sec: int = Field(default=10, gt=0)
    breaker_min_calls: int = Field(default=10, gt=0)
    breaker_failure_ratio: float = Field(default=0.5, gt=0, le=1)
    instance_id: str = Field(default_factory=socket.gethostname, min_length=1)
    protected_paths: list[str] = Field(default_factory=lambda: ["/demo"])
    log_level: str = "info"
    log_format: Literal["json", "text"] = "json"

    @property
    def limits_query_timeout_sec(self) -> float:
        return self.limits_query_timeout_ms / 1000

    @property
    def redis_queue_timeout_sec(self) -> float:
        return self.redis_queue_timeout_ms / 1000

    @property
    def redis_timeout_sec(self) -> float:
        return self.redis_timeout_ms / 1000

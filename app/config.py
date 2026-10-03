import socket

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    redis_url: str = "redis://redis:6379/0"
    rate_limit: int = Field(default=100, ge=0)
    window_sec: int = Field(default=60, gt=0)
    redis_timeout_ms: int = Field(default=500, gt=0)
    redis_max_connections: int = Field(default=64, gt=0)
    instance_id: str = Field(default_factory=socket.gethostname, min_length=1)
    log_level: str = "info"

    @property
    def redis_timeout_sec(self) -> float:
        return self.redis_timeout_ms / 1000

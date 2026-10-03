from dataclasses import dataclass
from enum import StrEnum


class DegradedReason(StrEnum):
    REDIS_UNAVAILABLE = "redis_unavailable"
    REDIS_TIMEOUT = "redis_timeout"
    OVERLOADED = "overloaded"


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    limit: int | None
    remaining: int | None
    reset_at: int | None
    retry_after: int | None
    degraded: DegradedReason | None = None

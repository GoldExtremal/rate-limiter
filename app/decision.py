from dataclasses import dataclass
from enum import StrEnum


class DegradedReason(StrEnum):
    REDIS_UNAVAILABLE = "redis_unavailable"
    OVERLOADED = "overloaded"


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    limit: int | None
    remaining: int | None
    reset_at: int | None
    retry_after: int | None
    degraded: DegradedReason | None = None

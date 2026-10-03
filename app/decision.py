from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    limit: int | None
    remaining: int | None
    reset_at: int | None
    retry_after: int | None

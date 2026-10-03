from pydantic import BaseModel, Field

from app.decision import DegradedReason

CLIENT_ID_MAX_LENGTH = 256


class CheckRequest(BaseModel):
    client_id: str = Field(min_length=1, max_length=CLIENT_ID_MAX_LENGTH)


class CheckResponse(BaseModel):
    allowed: bool
    remaining: int | None
    reset_at: int | None
    degraded: DegradedReason | None

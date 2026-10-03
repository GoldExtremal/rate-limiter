from fastapi import APIRouter, Request, Response

from app.limiter import RateLimiter
from app.schemas import CheckRequest, CheckResponse

router = APIRouter()


def get_limiter(request: Request) -> RateLimiter:
    limiter: RateLimiter = request.app.state.limiter
    return limiter


@router.get("/health")
async def health(request: Request) -> dict[str, object]:
    limits = get_limiter(request).limits
    return {
        "status": "ok",
        "instance": request.app.state.settings.instance_id,
        "limits_loaded": limits.loaded,
        "limits_count": limits.count,
    }


@router.get("/demo")
async def demo() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/check")
async def check(payload: CheckRequest, request: Request, response: Response) -> CheckResponse:
    decision = await get_limiter(request).check(payload.client_id)
    if decision.retry_after is not None:
        response.headers["Retry-After"] = str(decision.retry_after)
    return CheckResponse(
        allowed=decision.allowed,
        remaining=decision.remaining,
        reset_at=decision.reset_at,
    )

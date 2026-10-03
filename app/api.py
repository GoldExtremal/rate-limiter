from fastapi import APIRouter, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.limiter import RateLimiter
from app.middleware import DEGRADED_HEADER
from app.schemas import CheckRequest, CheckResponse

router = APIRouter()


def get_limiter(request: Request) -> RateLimiter:
    limiter: RateLimiter = request.app.state.limiter
    return limiter


@router.get("/health")
async def health(request: Request) -> dict[str, object]:
    limiter = get_limiter(request)
    limits = limiter.limits
    return {
        "status": "ok",
        "instance": request.app.state.settings.instance_id,
        "breaker": limiter.breaker.state.name.lower(),
        "limits_loaded": limits.loaded,
        "limits_count": limits.count,
        "limits_snapshot_age_sec": limits.snapshot_age_sec(),
    }


@router.get("/metrics")
async def metrics(request: Request) -> Response:
    registry = get_limiter(request).metrics.registry
    return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)


@router.get("/demo")
async def demo() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/check")
async def check(payload: CheckRequest, request: Request, response: Response) -> CheckResponse:
    decision = await get_limiter(request).check(payload.client_id, payload.request_id)
    if decision.retry_after is not None:
        response.headers["Retry-After"] = str(decision.retry_after)
    if decision.degraded is not None:
        response.headers[DEGRADED_HEADER] = decision.degraded
    return CheckResponse(
        allowed=decision.allowed,
        remaining=decision.remaining,
        reset_at=decision.reset_at,
        degraded=decision.degraded,
    )

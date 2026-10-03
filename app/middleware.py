from collections.abc import Iterable

from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.decision import Decision
from app.limiter import RateLimiter
from app.schemas import CLIENT_ID_MAX_LENGTH

CLIENT_ID_HEADER = b"x-client-id"
DEGRADED_HEADER = "X-RateLimit-Degraded"


def read_client_id(scope: Scope) -> str | None:
    for name, value in scope["headers"]:
        if name != CLIENT_ID_HEADER:
            continue
        try:
            client_id: str = value.decode("utf-8")
        except UnicodeDecodeError:
            return None
        return client_id if 1 <= len(client_id) <= CLIENT_ID_MAX_LENGTH else None
    return None


def rate_limit_headers(decision: Decision) -> dict[str, str]:
    values = {
        "X-RateLimit-Limit": decision.limit,
        "X-RateLimit-Remaining": decision.remaining,
        "X-RateLimit-Reset": decision.reset_at,
        "Retry-After": decision.retry_after,
        DEGRADED_HEADER: decision.degraded,
    }
    return {name: str(value) for name, value in values.items() if value is not None}


def rejection_response(decision: Decision, headers: dict[str, str]) -> JSONResponse:
    if decision.degraded is None:
        return JSONResponse({"detail": "rate limit exceeded"}, status_code=429, headers=headers)
    return JSONResponse(
        {"detail": f"rate limiter is degraded: {decision.degraded}"},
        status_code=503,
        headers=headers,
    )


class RateLimitMiddleware:
    def __init__(self, app: ASGIApp, protected_paths: Iterable[str]) -> None:
        self.app = app
        self.protected_paths = frozenset(protected_paths)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] not in self.protected_paths:
            await self.app(scope, receive, send)
            return

        client_id = read_client_id(scope)
        if client_id is None:
            response = JSONResponse(
                {"detail": "X-Client-Id header must be 1-256 UTF-8 characters"},
                status_code=400,
            )
            await response(scope, receive, send)
            return

        limiter: RateLimiter = scope["app"].state.limiter
        decision = await limiter.check(client_id)
        headers = rate_limit_headers(decision)

        if not decision.allowed:
            await rejection_response(decision, headers)(scope, receive, send)
            return

        async def send_with_rate_limit_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                for name, value in headers.items():
                    response_headers[name] = value
            await send(message)

        await self.app(scope, receive, send_with_rate_limit_headers)

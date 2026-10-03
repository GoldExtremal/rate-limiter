from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

INSTANCE_ID_HEADER = "X-Instance-Id"


class InstanceIdASGI:
    def __init__(self, app: ASGIApp, instance_id: str) -> None:
        self.app = app
        self.instance_id = instance_id

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_instance_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message).append(INSTANCE_ID_HEADER, self.instance_id)
            await send(message)

        await self.app(scope, receive, send_with_instance_id)

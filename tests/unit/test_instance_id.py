from fastapi import FastAPI
from pydantic import BaseModel

from app.instance import INSTANCE_ID_HEADER, InstanceIdASGI
from tests.conftest import make_client


class Payload(BaseModel):
    value: int


def build_app() -> InstanceIdASGI:
    inner = FastAPI()

    @inner.get("/ok")
    async def ok() -> dict[str, str]:
        return {"status": "ok"}

    @inner.post("/validated")
    async def validated(payload: Payload) -> Payload:
        return payload

    @inner.get("/boom")
    async def boom() -> None:
        raise RuntimeError("unhandled")

    return InstanceIdASGI(inner, "unit-instance")


async def test_header_is_added_to_every_kind_of_response() -> None:
    async with make_client(build_app()) as client:
        responses = [
            await client.get("/ok"),
            await client.get("/missing"),
            await client.post("/validated", json={"value": "not-a-number"}),
            await client.get("/boom"),
        ]

    assert [response.status_code for response in responses] == [200, 404, 422, 500]
    assert all(r.headers[INSTANCE_ID_HEADER] == "unit-instance" for r in responses)

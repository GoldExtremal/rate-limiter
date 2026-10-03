import pytest

from tests.conftest import ClientFactory

DISTINCT_IDS = ["user@example.com", "user 1", "пользователь", "{tenant}:42", "a/b", " a", "a"]


async def test_any_string_works_as_independent_client_id(app_client: ClientFactory) -> None:
    async with app_client(rate_limit=1) as client:
        first = [await client.post("/check", json={"client_id": i}) for i in DISTINCT_IDS]
        second = [await client.post("/check", json={"client_id": i}) for i in DISTINCT_IDS]

    assert all(response.json()["allowed"] is True for response in first)
    assert all(response.json()["allowed"] is False for response in second)


@pytest.mark.parametrize(("client_id", "status"), [("x" * 256, 200), ("x" * 257, 422), ("", 422)])
async def test_client_id_length_is_validated(
    app_client: ClientFactory, client_id: str, status: int
) -> None:
    async with app_client() as client:
        response = await client.post("/check", json={"client_id": client_id})

    assert response.status_code == status


async def test_check_response_contract(app_client: ClientFactory) -> None:
    async with app_client() as client:
        response = await client.post("/check", json={"client_id": "contract"})

    assert response.status_code == 200
    assert set(response.json()) == {"allowed", "remaining", "reset_at"}

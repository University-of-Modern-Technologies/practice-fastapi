"""The error envelope is part of the published contract, so it is asserted
directly rather than inferred from status codes alone."""

from __future__ import annotations

from httpx import AsyncClient

from app.middleware.request_id import REQUEST_ID_HEADER


async def test_app_error_carries_code_details_and_request_id(client: AsyncClient) -> None:
    response = await client.get("/probe/conflict")

    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "CONTACT_EXISTS"
    assert body["error"]["message"] == "Contact already exists"
    assert body["error"]["details"] == {"field": "email"}
    assert body["requestId"] == response.headers[REQUEST_ID_HEADER]


async def test_details_are_omitted_when_absent(client: AsyncClient) -> None:
    response = await client.get("/missing-route")

    assert response.status_code == 404
    assert "details" not in response.json()["error"]


async def test_unmatched_route_names_the_method_and_path(client: AsyncClient) -> None:
    response = await client.get("/missing-route")

    body = response.json()
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["error"]["message"] == "Route GET /missing-route not found"


async def test_schema_violation_is_400_not_422(client: AsyncClient) -> None:
    response = await client.post("/probe/echo", json={"email": "a", "age": -1})

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"

    field_errors = body["error"]["details"]["fieldErrors"]["body"]
    assert any(entry.startswith("email:") for entry in field_errors)
    assert any(entry.startswith("age:") for entry in field_errors)


async def test_malformed_json_is_distinguished_from_a_wrong_shape(client: AsyncClient) -> None:
    response = await client.post(
        "/probe/echo",
        content=b"{not json",
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_JSON"


async def test_unhandled_error_is_masked_in_production(client: AsyncClient) -> None:
    response = await client.get("/probe/unhandled")

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "INTERNAL_SERVER_ERROR"
    # Outside production the cause is echoed so a developer can see it.
    assert "something went wrong internally" in body["error"]["message"]


async def test_oversized_body_is_rejected(client: AsyncClient) -> None:
    payload = {"email": "user@example.com", "age": 30, "padding": "x" * 2_000_000}

    response = await client.post("/probe/echo", json=payload)

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"

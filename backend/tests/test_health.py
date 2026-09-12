import json
import logging

from fastapi import APIRouter
from fastapi.testclient import TestClient
from app.main import create_app

def test_health():
    response = TestClient(create_app()).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_request_id_is_returned_and_used_in_structured_log(caplog):
    with caplog.at_level(logging.INFO, logger="career_assessment.requests"):
        response = TestClient(create_app()).get(
            "/health?candidate=private",
            headers={"X-Request-ID": "client-controlled", "Authorization": "Bearer secret"},
        )

    request_id = response.headers["X-Request-ID"]
    assert request_id != "client-controlled"
    event = json.loads(caplog.records[-1].message)
    assert event == {
        "event": "request.completed",
        "method": "GET",
        "path": "/health",
        "statusCode": 200,
        "requestId": request_id,
    }
    assert "private" not in caplog.text
    assert "secret" not in caplog.text


def test_not_found_uses_standard_error_contract():
    response = TestClient(create_app()).get("/api/v1/missing")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "NOT_FOUND",
            "message": "Resource not found",
            "requestId": response.headers["X-Request-ID"],
            "details": {},
        }
    }


def test_validation_error_uses_standard_error_contract_without_user_input():
    router = APIRouter()

    @router.get("/example")
    async def example(limit: int) -> dict[str, int]:
        return {"limit": limit}

    response = TestClient(create_app(api_router=router)).get("/api/v1/example?limit=private-value")

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "INPUT_INVALID"
    assert body["error"]["requestId"] == response.headers["X-Request-ID"]
    assert body["error"]["details"] == {"fields": [{"location": ["query", "limit"], "type": "int_parsing"}]}
    assert "private-value" not in response.text


def test_unhandled_error_is_sanitized_and_uses_standard_contract(caplog):
    router = APIRouter()

    @router.get("/explode")
    async def explode() -> None:
        raise RuntimeError("secret user content")

    with caplog.at_level(logging.ERROR, logger="career_assessment.requests"):
        response = TestClient(create_app(api_router=router), raise_server_exceptions=False).get("/api/v1/explode")

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "INTERNAL_ERROR",
            "message": "Internal server error",
            "requestId": response.headers["X-Request-ID"],
            "details": {},
        }
    }
    assert "secret user content" not in caplog.text


def test_cors_allows_only_configured_same_origin(monkeypatch):
    monkeypatch.setenv("FRONTEND_ORIGIN", "https://assessment.example")
    client = TestClient(create_app())

    allowed = client.options(
        "/health",
        headers={"Origin": "https://assessment.example", "Access-Control-Request-Method": "GET"},
    )
    denied = client.options(
        "/health",
        headers={"Origin": "https://attacker.example", "Access-Control-Request-Method": "GET"},
    )

    assert allowed.headers["Access-Control-Allow-Origin"] == "https://assessment.example"
    assert "Access-Control-Allow-Origin" not in denied.headers

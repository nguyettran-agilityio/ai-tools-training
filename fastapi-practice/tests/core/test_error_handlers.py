"""Tests for app.core.error_handlers.register_exception_handlers.

Uses a throwaway app + router mounted here (not the real app/module routers)
so the handlers are exercised in isolation.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.error_handlers import register_exception_handlers
from app.core.exceptions import ConflictError, NotFoundError


class _ItemPayload(BaseModel):
    name: str
    quantity: int


def _build_test_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom/not-found")
    def raise_not_found():
        raise NotFoundError("Book not found.")

    @app.get("/boom/conflict")
    def raise_conflict():
        raise ConflictError("Book already exists.")

    @app.get("/boom/unhandled")
    def raise_unhandled():
        raise RuntimeError("some sensitive internal detail")

    @app.post("/items")
    def create_item(payload: _ItemPayload):
        return {"ok": True}

    return app


client = TestClient(_build_test_app(), raise_server_exceptions=False)


def test_not_found_error_returns_404_with_error_shape():
    response = client.get("/boom/not-found")

    assert response.status_code == 404
    body = response.json()
    assert set(body.keys()) == {"code", "message", "errors"}
    assert body == {
        "code": "NOT_FOUND",
        "message": "Book not found.",
        "errors": None,
    }


def test_conflict_error_returns_409_with_error_shape():
    response = client.get("/boom/conflict")

    assert response.status_code == 409
    body = response.json()
    assert set(body.keys()) == {"code", "message", "errors"}
    assert body == {
        "code": "CONFLICT",
        "message": "Book already exists.",
        "errors": None,
    }


def test_invalid_body_returns_422_with_field_errors():
    """Missing "quantity" triggers RequestValidationError; the leading "body"
    loc segment must be stripped from the field name."""
    response = client.post("/items", json={"name": "Book"})

    assert response.status_code == 422
    body = response.json()
    assert set(body.keys()) == {"code", "message", "errors"}
    assert body["code"] == "VALIDATION_ERROR"
    assert body["errors"] == [{"field": "quantity", "message": "Field required"}]


def test_unhandled_exception_returns_500_without_leaking_details():
    response = client.get("/boom/unhandled")

    assert response.status_code == 500
    body = response.json()
    assert set(body.keys()) == {"code", "message", "errors"}
    assert body["code"] == "INTERNAL_SERVER_ERROR"
    assert "sensitive internal detail" not in body["message"]

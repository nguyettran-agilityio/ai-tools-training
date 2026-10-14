"""Tests for app.core.middleware.RequestContextMiddleware (X-Request-ID)."""

import uuid

from app.core.middleware import REQUEST_ID_HEADER


def test_response_contains_x_request_id_header(client):
    response = client.get("/health")

    assert REQUEST_ID_HEADER in response.headers
    # No incoming header was sent, so the middleware must have generated one —
    # a valid uuid4 string.
    assert uuid.UUID(response.headers[REQUEST_ID_HEADER]).version == 4


def test_provided_x_request_id_is_echoed_back_unchanged(client):
    incoming_id = "test-request-id-12345"

    response = client.get("/health", headers={REQUEST_ID_HEADER: incoming_id})

    assert response.headers[REQUEST_ID_HEADER] == incoming_id

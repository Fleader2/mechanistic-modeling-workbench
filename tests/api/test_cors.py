"""Tests for the frontend/backend CORS configuration (``app/main.py``).

The frontend (``frontend/``, a separately-run Vite dev server) and this API
are two different origins during local development -- without CORS, every
browser ``fetch`` call the frontend makes is silently blocked by the
browser itself before the backend ever sees it, independent of whether the
backend and tests agree the request is otherwise correct.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config.settings import API_V1_PREFIX

pytestmark = pytest.mark.api

HEALTH_URL = f"{API_V1_PREFIX}/health"


def test_allowed_frontend_origin_receives_cors_header(client: TestClient) -> None:
    response = client.get(HEALTH_URL, headers={"Origin": "http://localhost:5173"})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_unconfigured_origin_receives_no_cors_header(client: TestClient) -> None:
    response = client.get(HEALTH_URL, headers={"Origin": "http://evil.example.com"})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_preflight_request_for_allowed_origin_is_permitted(client: TestClient) -> None:
    response = client.options(
        HEALTH_URL,
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"

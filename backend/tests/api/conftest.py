from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRouter
from fastapi.testclient import TestClient


@pytest.fixture
def build_client() -> Generator[Any, None, None]:
    clients: list[TestClient] = []

    def _build(
        *,
        router: APIRouter,
        prefix: str = "",
        dependency_overrides: dict[Any, Any] | None = None,
    ) -> TestClient:
        app = FastAPI()
        app.include_router(router, prefix=prefix)
        if dependency_overrides:
            app.dependency_overrides.update(dependency_overrides)
        client = TestClient(app)
        clients.append(client)
        return client

    try:
        yield _build
    finally:
        for client in clients:
            client.close()

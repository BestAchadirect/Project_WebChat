from __future__ import annotations

import pytest

pytest.importorskip("pydantic_settings")

from app.api.routes.analytics import router
from app.dependencies import get_db


async def override_get_db():
    return object()


def test_chat_click_tracking_endpoint_accepts_payload(build_client) -> None:
    client = build_client(
        router=router,
        prefix="/api/v1/analytics",
        dependency_overrides={get_db: override_get_db},
    )

    response = client.post(
        "/api/v1/analytics/chat-clicks",
        json={
            "conversation_id": 123,
            "qa_log_id": "qa-1",
            "product_id": "prod-1",
            "sku": "SKU-1",
            "rank": 2,
            "timestamp": "2026-03-11T10:15:00Z",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"saved": True}

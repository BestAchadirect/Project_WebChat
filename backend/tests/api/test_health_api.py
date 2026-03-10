from __future__ import annotations

from app.api.routes.health import router


def test_health_endpoint_returns_expected_payload(build_client) -> None:
    client = build_client(router=router)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "service": "GenAI SaaS Backend"}


def test_root_endpoint_returns_welcome_message(build_client) -> None:
    client = build_client(router=router)

    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {"message": "Welcome to GenAI SaaS API"}

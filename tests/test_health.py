"""Smoke test: the FastAPI app imports and /health responds."""
from fastapi.testclient import TestClient

from app.main import api


def test_health_ok():
    client = TestClient(api)
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["db_backend"] == "in-memory"
    assert body["llm_mode"] in {"heuristic", "openrouter"}

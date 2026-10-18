from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.main import app


def test_health_reports_pgvector(engine: Engine) -> None:
    response = TestClient(app).get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["pgvector"]

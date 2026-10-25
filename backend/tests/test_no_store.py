"""API responses are never cached, so nothing is shown again after signing out."""


def test_api_responses_are_not_stored(client_for) -> None:
    client = client_for("judge")
    assert client.get("/api/v1/me").headers["cache-control"] == "no-store"
    assert client.get("/api/v1/health").headers["cache-control"] == "no-store"

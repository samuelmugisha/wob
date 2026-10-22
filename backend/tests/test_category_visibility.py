"""Hiding an award category, such as a test category, from lists without deleting anything."""

from tests.test_knowledge_base import make_candidate, make_category


def test_admin_hides_and_shows_a_category(client_for, coordinator) -> None:
    admin = client_for("admin")
    category = make_category(coordinator)
    make_candidate(coordinator, category["id"], "Test Person")
    url = f"/api/v1/categories/{category['id']}/visibility"

    def listed(client, path="/api/v1/categories") -> bool:
        return category["id"] in {c["id"] for c in client.get(path).json()}

    assert coordinator.put(url, json={"hidden": True}).status_code == 403
    hidden = admin.put(url, json={"hidden": True})
    assert hidden.status_code == 200, hidden.text
    assert hidden.json()["hidden_at"]

    judge = client_for("judge")
    assert not listed(judge)
    assert listed(admin, "/api/v1/categories?include_hidden=true")
    dashboard = judge.get("/api/v1/dashboard").json()
    assert category["id"] not in {c["id"] for c in dashboard["by_category"]}
    assert category["id"] not in {c["id"] for c in judge.get("/api/v1/judges-pack").json()}
    # Nothing is deleted, and its own link still works.
    assert judge.get(f"/api/v1/categories/{category['id']}").json()["hidden_at"]
    assert len(judge.get(f"/api/v1/categories/{category['id']}/finalists").json()) == 1

    shown = admin.put(url, json={"hidden": False})
    assert shown.status_code == 200 and shown.json()["hidden_at"] is None
    assert listed(judge)

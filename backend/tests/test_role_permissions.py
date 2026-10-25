"""Administrators set the rights of each user group."""

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text

URL = "/api/v1/role-permissions"
DEFAULTS = {
    "secretariat": [
        "export_personal_data",
        "generate_reports",
        "manage_calibration",
        "manage_evidence",
        "review_claims",
    ],
    "reviewer": ["rate_calibration", "review_claims"],
    "judge": ["rate_calibration"],
    "committee": ["approve_rubrics", "generate_reports", "manage_calibration", "rate_calibration"],
}


@pytest.fixture(autouse=True)
def _restore_defaults(engine: Engine) -> Iterator[None]:
    """The rights are shared by every test, so put back the ones the migration seeds."""
    yield
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM role_permissions"))
        for role, granted in DEFAULTS.items():
            for permission in granted:
                conn.execute(
                    text("INSERT INTO role_permissions VALUES (:r, :p)"),
                    {"r": role, "p": permission},
                )


def test_defaults_keep_the_rights_each_group_had(client_for) -> None:
    body = client_for("admin").get(URL).json()
    assert {g["role"]: g["permissions"] for g in body["groups"]} == DEFAULTS
    assert len(body["permissions"]) == 7 and all(p["label"] for p in body["permissions"])


def test_only_an_admin_sees_or_changes_rights(client_for) -> None:
    for role in ("secretariat", "reviewer", "judge", "committee"):
        client = client_for(role)
        assert client.get(URL).status_code == 403
        assert client.put(f"{URL}/judge", json={"permissions": []}).status_code == 403
    admin = client_for("admin")
    assert admin.put(f"{URL}/admin", json={"permissions": []}).status_code == 422
    assert admin.put(f"{URL}/judge", json={"permissions": ["delete_everything"]}).status_code == 422


def test_granting_and_removing_rights_takes_effect_at_once(client_for, engine) -> None:
    admin = client_for("admin")
    judge = client_for("judge")
    coordinator = client_for("secretariat")
    assert judge.get("/api/v1/me").json()["permissions"]["generate_reports"] is False

    granted = admin.put(f"{URL}/judge", json={"permissions": ["generate_reports"]})
    assert granted.status_code == 200, granted.text
    me = judge.get("/api/v1/me").json()["permissions"]
    assert me["generate_reports"] is True and me["rate_calibration"] is False

    kept = ["generate_reports", "review_claims"]
    removed = admin.put(f"{URL}/secretariat", json={"permissions": kept})
    assert removed.status_code == 200
    new_category = coordinator.post("/api/v1/categories", json={"code": "x1", "name": "X"})
    assert new_category.status_code == 403
    # Administrators keep every right whatever the groups hold.
    assert admin.get("/api/v1/me").json()["permissions"]["export_personal_data"] is True

    with engine.connect() as conn:
        details = conn.scalar(
            text(
                "SELECT details FROM audit_events WHERE action = 'role.permissions_updated' "
                "ORDER BY id DESC LIMIT 1"
            )
        )
    assert details["role"] == "secretariat"
    assert details["after"] == kept
    assert set(details["before"]) - set(kept) == {
        "export_personal_data",
        "manage_calibration",
        "manage_evidence",
    }


def test_calibration_raters_follow_the_rating_right(client_for) -> None:
    admin = client_for("admin")
    client_for("secretariat")
    client_for("judge")
    roles = lambda: {r["role"] for r in admin.get("/api/v1/calibration/eligible-raters").json()}  # noqa: E731
    assert "secretariat" not in roles() and "judge" in roles()
    admin.put(f"{URL}/secretariat", json={"permissions": ["rate_calibration"]})
    admin.put(f"{URL}/judge", json={"permissions": []})
    assert "secretariat" in roles() and "judge" not in roles()

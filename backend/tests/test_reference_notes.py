"""Notes from a finalist's references: up to four, each a referee's name and what they said."""

import io
import json
import zipfile

from sqlalchemy import Engine, text

from tests.test_knowledge_base import make_candidate, make_category, record_consent


def url(category: dict, candidate: dict) -> str:
    return f"/api/v1/categories/{category['id']}/finalists/{candidate['id']}/reference-notes"


def test_coordinators_record_up_to_four_reference_notes(client_for, coordinator, engine) -> None:
    category = make_category(coordinator)
    jane = make_candidate(coordinator, category["id"])
    notes_url = url(category, jane)
    assert coordinator.get(notes_url).json() == []

    body = {
        "notes": [
            {"referee_name": "Grace Referee", "notes": "Chaired our audit committee with rigour."},
            {"referee_name": "Paul Referee", "notes": "Mentored three of our managers."},
        ]
    }
    saved = coordinator.put(notes_url, json=body)
    assert saved.status_code == 200, saved.text
    assert [(n["position"], n["referee_name"]) for n in saved.json()] == [
        (1, "Grace Referee"),
        (2, "Paul Referee"),
    ]
    assert saved.json()[0]["updated_by"] == "Test"

    # Editing replaces the list: the second is removed, the first reworded.
    body["notes"] = [{"referee_name": "Grace Referee", "notes": "  Chaired the audit committee. "}]
    edited = coordinator.put(notes_url, json=body).json()
    assert [(n["referee_name"], n["notes"]) for n in edited] == [
        ("Grace Referee", "Chaired the audit committee.")
    ]

    five = {"notes": [{"referee_name": f"R{i}", "notes": "Good."} for i in range(5)]}
    assert coordinator.put(notes_url, json=five).status_code == 422
    blank = {"notes": [{"referee_name": " ", "notes": "Good."}]}
    assert coordinator.put(notes_url, json=blank).status_code == 422

    judge = client_for("judge")
    assert judge.get(notes_url).status_code == 200
    assert judge.put(notes_url, json=body).status_code == 403
    with engine.connect() as conn:
        assert conn.execute(
            text("SELECT count(*) FROM audit_events WHERE action = 'reference_notes.saved'")
        ).scalar_one()


def test_withdrawn_consent_blocks_new_notes(coordinator) -> None:
    category = make_category(coordinator)
    jane = make_candidate(coordinator, category["id"])
    record_consent(
        coordinator,
        category["id"],
        jane["id"],
        assessment=False,
        ai_processing=False,
        web_research=False,
    )
    response = coordinator.put(
        url(category, jane), json={"notes": [{"referee_name": "A", "notes": "B"}]}
    )
    assert response.status_code == 409


def test_notes_are_exported_and_purged(client_for, coordinator, engine: Engine) -> None:
    category = make_category(coordinator)
    jane = make_candidate(coordinator, category["id"], "Jane Doe")
    coordinator.put(
        url(category, jane), json={"notes": [{"referee_name": "Grace", "notes": "Strong."}]}
    )
    base = f"/api/v1/categories/{category['id']}/finalists/{jane['id']}"
    export = coordinator.get(f"{base}/export")
    with zipfile.ZipFile(io.BytesIO(export.content)) as zf:
        data = json.loads(zf.read("data.json"))
    assert data["reference_notes"][0] == {
        "referee": "Grace",
        "notes": "Strong.",
        "recorded_at": data["reference_notes"][0]["recorded_at"],
    }

    purged = client_for("admin").post(
        f"{base}/purge", json={"reason": "erasure request", "confirm_name": "Jane Doe"}
    )
    assert purged.status_code == 200, purged.text
    with engine.connect() as conn:
        assert not conn.execute(
            text("SELECT count(*) FROM reference_notes WHERE finalist_category_id = :fc"),
            {"fc": jane["finalist_category_id"]},
        ).scalar_one()

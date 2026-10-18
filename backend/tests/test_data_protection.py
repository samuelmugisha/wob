"""Consent records, human-only assessment, subject-access export and purge
(docs/operations/data-protection-review.md §4.1, §4.5, §4.10)."""

import io
import json
import zipfile
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.main import app
from app.services.purge import purge_expired
from app.services.storage import build_storage
from tests import fixture_files, test_assessment
from tests.conftest import drain
from tests.test_assessment import JANE, MARY, assess, items_for
from tests.test_knowledge_base import (
    make_candidate,
    make_category,
    pdf,
    record_consent,
    upload,
)

_empty_queues = test_assessment._empty_queues


def candidate_url(category: dict, candidate: dict) -> str:
    return f"/api/v1/categories/{category['id']}/finalists/{candidate['id']}"


# --- Consent ---------------------------------------------------------------------------------


def test_consent_before_upload_is_optional_by_default(coordinator: TestClient) -> None:
    category = make_category(coordinator)
    jane = make_candidate(coordinator, category["id"], consent={})
    assert upload(coordinator, category["id"], jane["id"], [("n.pdf", pdf())]).status_code == 202

    # An explicit withdrawal still stops uploads.
    record_consent(
        coordinator,
        category["id"],
        jane["id"],
        assessment=False,
        ai_processing=False,
        web_research=False,
    )
    blocked = upload(coordinator, category["id"], jane["id"], [("m.pdf", pdf())])
    assert blocked.status_code == 409 and "withdrawn" in blocked.json()["detail"]


def test_uploads_need_assessment_consent_when_required(coordinator: TestClient) -> None:
    app.dependency_overrides[get_settings]().upload_requires_consent = True
    category = make_category(coordinator)
    jane = make_candidate(coordinator, category["id"], consent={})
    blocked = upload(coordinator, category["id"], jane["id"], [("n.pdf", pdf())])
    assert blocked.status_code == 409 and "part A" in blocked.json()["detail"]

    record_consent(coordinator, category["id"], jane["id"], ai_processing=False, web_research=False)
    assert upload(coordinator, category["id"], jane["id"], [("n.pdf", pdf())]).status_code == 202

    # Withdrawal is a new record; uploads stop again and the history is kept.
    record_consent(
        coordinator,
        category["id"],
        jane["id"],
        assessment=False,
        ai_processing=False,
        web_research=False,
    )
    assert upload(coordinator, category["id"], jane["id"], [("m.pdf", pdf())]).status_code == 409
    history = coordinator.get(f"{candidate_url(category, jane)}/consent").json()["history"]
    assert [h["assessment"] for h in history] == [False, True]
    listed = coordinator.get(f"/api/v1/categories/{category['id']}/finalists").json()
    assert listed[0]["consent"] == {
        "assessment": False,
        "ai_processing": False,
        "web_research": False,
    }


def test_consent_rules(client_for, coordinator: TestClient, engine: Engine) -> None:
    category = make_category(coordinator)
    jane = make_candidate(coordinator, category["id"], consent={})
    url = f"{candidate_url(category, jane)}/consent"
    body = {
        "notice_version": "v1",
        "method": "email",
        "assessment": False,
        "ai_processing": True,
        "web_research": False,
    }
    assert coordinator.post(url, json=body).status_code == 422  # AI without assessment
    assert client_for("judge").post(url, json={**body, "assessment": True}).status_code == 403
    with engine.begin() as conn, pytest.raises(Exception, match="append-only"):
        record_consent(coordinator, category["id"], jane["id"])
        conn.execute(text("UPDATE finalist_consents SET ai_processing = false"))


def test_ai_features_need_ai_and_research_consent(coordinator: TestClient, make_pipeline) -> None:
    category = make_category(coordinator)
    jane = make_candidate(
        coordinator,
        category["id"],
        consent={"assessment": True, "ai_processing": False, "web_research": False},
    )
    upload(coordinator, category["id"], jane["id"], [("cv.docx", fixture_files.docx_document())])
    drain(make_pipeline())
    extract = coordinator.post(f"{candidate_url(category, jane)}/claims/extract")
    assert extract.status_code == 409 and "part B" in extract.json()["detail"]


# --- Human-only assessment ---------------------------------------------------------------------


@pytest.fixture
def mixed_world(coordinator: TestClient, make_pipeline) -> dict:
    """Jane consented to AI; Mary only to assessment."""
    category = make_category(coordinator)
    jane = make_candidate(coordinator, category["id"], "Jane Doe")
    mary = make_candidate(
        coordinator,
        category["id"],
        "Mary Major",
        consent={"assessment": True, "ai_processing": False, "web_research": False},
    )
    for person, sections in ((jane, JANE), (mary, MARY)):
        upload(
            coordinator,
            category["id"],
            person["id"],
            [("evidence.docx", fixture_files.docx_from(sections))],
        )
    drain(make_pipeline())
    rubric = coordinator.post(
        f"/api/v1/categories/{category['id']}/rubrics", json={"use_template": True}
    ).json()
    return {
        "category": category,
        "people": {"Jane Doe": jane, "Mary Major": mary},
        "rubric": rubric,
    }


def test_finalists_without_ai_consent_are_rated_by_people(
    client_for, coordinator, mixed_world, engine
) -> None:
    run, assessor = assess(coordinator, mixed_world, engine)
    status = coordinator.get(f"/api/v1/assessments/{run['id']}").json()
    assert status["items_total"] == 5 and status["status"] == "succeeded"
    assert status["skipped"][0]["finalist"] == "Mary Major"
    assert all("Mary Major" not in user for _, user in assessor.calls)  # never sent to the AI
    assert items_for(coordinator, mixed_world, "Mary Major") == {}

    reviewer = client_for("reviewer")
    mary_id = mixed_world["people"]["Mary Major"]["id"]
    for criterion in mixed_world["rubric"]["criteria"]:
        response = reviewer.post(
            "/api/v1/criterion-assessments/human",
            json={
                "run_id": run["id"],
                "finalist_id": mary_id,
                "criterion_id": criterion["id"],
                "rating": 4,
                "rationale": "Read the evidence: strong board track record.",
                "sufficiency": "sufficient",
            },
        )
        assert response.status_code == 201, response.text
        assert response.json()["source"] == "human"
        assert response.json()["status"] == "approved"
    again = reviewer.post(
        "/api/v1/criterion-assessments/human",
        json={
            "run_id": run["id"],
            "finalist_id": mary_id,
            "criterion_id": mixed_world["rubric"]["criteria"][0]["id"],
            "rating": 2,
            "rationale": "A second opinion here.",
            "sufficiency": "limited",
        },
    )
    assert again.status_code == 409
    assert (
        client_for("judge")
        .post(
            "/api/v1/criterion-assessments/human",
            json={
                "run_id": run["id"],
                "finalist_id": mary_id,
                "criterion_id": mixed_world["rubric"]["criteria"][0]["id"],
                "rating": 2,
                "rationale": "Judges cannot do this.",
                "sufficiency": "limited",
            },
        )
        .status_code
        == 403
    )

    ranking = coordinator.post(
        "/api/v1/rankings", json={"category_id": mixed_world["category"]["id"]}
    ).json()
    scores = {e["full_name"]: e["score_display"] for e in ranking["entries"]}
    assert scores == {"Mary Major": "4.00", "Jane Doe": "3.20"}


def test_human_only_runs_work_with_ai_switched_off(client_for, coordinator, mixed_world) -> None:
    from app.config import get_settings
    from app.main import app

    settings = app.dependency_overrides[get_settings]().model_copy(
        update={"llm_provider": "disabled"}
    )
    app.dependency_overrides[get_settings] = lambda: settings
    assert (
        coordinator.post(
            "/api/v1/assessments", json={"category_id": mixed_world["category"]["id"]}
        ).status_code
        == 403
    )
    run = coordinator.post(
        "/api/v1/assessments", json={"category_id": mixed_world["category"]["id"], "mode": "human"}
    )
    assert run.status_code == 202
    assert run.json()["status"] == "succeeded" and run.json()["llm_model"] == "human"


# --- Subject-access export ---------------------------------------------------------------------


def test_subject_access_export(client_for, coordinator, mixed_world, engine) -> None:
    run, _ = assess(coordinator, mixed_world, engine)
    reviewer = client_for("reviewer")
    item = items_for(reviewer, mixed_world, "Jane Doe")["advancing-women"]
    reviewer.post(
        f"/api/v1/criterion-assessments/{item['id']}/review", json={"decision": "approved"}
    )
    jane = mixed_world["people"]["Jane Doe"]
    url = f"{candidate_url(mixed_world['category'], jane)}/export"

    assert reviewer.get(url).status_code == 403
    response = coordinator.get(url)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        names = zf.namelist()
        data = json.loads(zf.read("data.json"))
        original = zf.read(next(n for n in names if n.startswith("documents/")))
    assert "README.txt" in names
    assert original.startswith(b"PK")  # the decrypted .docx
    assert data["finalist"]["name"] == "Jane Doe"
    assert data["consents"][0]["ai_processing"] is True
    assert len(data["criterion_assessments"]) == 5
    approved = next(a for a in data["criterion_assessments"] if a["status"] == "approved")
    assert approved["reviewed_by_role"] == "reviewer"
    assert "Test" not in json.dumps(data)  # no other individual named (s.24(4))
    assert data["recipients"]["processors"]  # AI processing is disclosed
    assert any(e["action"] == "documents.uploaded" for e in data["access_log"])
    with engine.connect() as conn:
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM audit_events WHERE action = 'subject_access.exported' "
                    "AND entity_id = :fc"
                ),
                {"fc": jane["finalist_category_id"]},
            ).scalar_one()
            == 1
        )


# --- Purge and retention -----------------------------------------------------------------------

FC_TABLES = [
    "documents",
    "document_chunks",
    "claims",
    "claim_evidence",
    "external_sources",
    "criterion_assessments",
    "assessment_citations",
    "ranking_entries",
    "calibration_items",
    "finalist_consents",
    "imports",
    "claim_extraction_runs",
    "research_runs",
]


def rows_for(engine: Engine, fc_id: str) -> dict[str, int]:
    with engine.connect() as conn:
        return {
            table: conn.execute(
                text(f"SELECT count(*) FROM {table} WHERE finalist_category_id = :fc"),
                {"fc": fc_id},
            ).scalar_one()
            for table in FC_TABLES
            if table != "claim_evidence"
        } | {
            "claim_evidence": conn.execute(
                text("SELECT count(*) FROM claim_evidence WHERE finalist_category_id = :fc"),
                {"fc": fc_id},
            ).scalar_one()
        }


def test_purge_erases_one_finalist_completely(
    client_for, coordinator, mixed_world, engine, tmp_path: Path
) -> None:
    run, _ = assess(coordinator, mixed_world, engine)
    category_id = mixed_world["category"]["id"]
    coordinator.post("/api/v1/rankings", json={"category_id": category_id})
    jane = mixed_world["people"]["Jane Doe"]
    mary = mixed_world["people"]["Mary Major"]
    coordinator.post(
        "/api/v1/reports",
        json={"kind": "individual", "category_id": category_id, "finalist_id": jane["id"]},
    )
    coordinator.post("/api/v1/reports", json={"kind": "category", "category_id": category_id})
    files_before = {p.name for p in (tmp_path / "storage").rglob("*") if p.is_file()}
    assert rows_for(engine, jane["finalist_category_id"])["criterion_assessments"] == 5

    admin = client_for("admin")
    url = f"{candidate_url(mixed_world['category'], jane)}/purge"
    assert (
        coordinator.post(
            url, json={"reason": "erasure request 1", "confirm_name": "Jane Doe"}
        ).status_code
        == 403
    )
    assert (
        admin.post(url, json={"reason": "erasure request 1", "confirm_name": "Jane"}).status_code
        == 422
    )
    response = admin.post(url, json={"reason": "erasure request 1", "confirm_name": "jane doe"})
    assert response.status_code == 200, response.text
    counts = response.json()["counts"]
    assert counts["documents"] == 1 and counts["criterion_assessments"] == 5
    assert counts["files_shredded"] == 3  # her document, her report, the category report

    assert set(rows_for(engine, jane["finalist_category_id"]).values()) == {0}
    with engine.connect() as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM finalists WHERE id = :f"), {"f": jane["id"]}
            ).scalar_one()
            == 0
        )
        # Every event about her (other than the purge record) is redacted, and no event
        # anywhere still carries her nomination id. (Other tests' "Jane Doe"s share the DB.)
        leftovers = conn.execute(
            text(
                "SELECT count(*) FROM audit_events WHERE action <> 'data.purged' AND "
                "((entity_id = :fc_id AND details::text NOT LIKE '%personal data purged%') "
                " OR details::text LIKE :fc)"
            ),
            {"fc_id": jane["finalist_category_id"], "fc": f"%{jane['finalist_category_id']}%"},
        ).scalar_one()
        purge_event = (
            conn.execute(text("SELECT details FROM audit_events WHERE action = 'data.purged'"))
            .scalars()
            .all()[-1]
        )
        reports_left = conn.execute(
            text("SELECT count(*) FROM reports WHERE category_id = :c"), {"c": category_id}
        ).scalar_one()
    assert leftovers == 0
    assert purge_event["reason"] == "erasure request 1" and "Jane" not in json.dumps(purge_event)
    assert reports_left == 0  # category reports named her

    files_after = {p.name for p in (tmp_path / "storage").rglob("*") if p.is_file()}
    assert len(files_before - files_after) == 3
    # Mary is untouched, and the immutability rules are back in force.
    assert rows_for(engine, mary["finalist_category_id"])["documents"] == 1
    with engine.connect() as conn, pytest.raises(Exception, match="append-only"):
        conn.execute(text("DELETE FROM audit_events"))


def test_purge_expired_follows_the_retention_date(
    client_for, coordinator, mixed_world, engine, tmp_path: Path
) -> None:
    from app.config import get_settings
    from app.main import app

    admin = client_for("admin")
    category_id = mixed_world["category"]["id"]
    url = f"/api/v1/categories/{category_id}/retention"
    assert coordinator.put(url, json={"retention_until": "2027-01-31"}).status_code == 403
    admin.put(url, json={"retention_until": (date.today() + timedelta(days=30)).isoformat()})
    settings = app.dependency_overrides[get_settings]()
    with Session(engine) as session:
        assert purge_expired(session, build_storage(settings)) == {}
    admin.put(url, json={"retention_until": (date.today() - timedelta(days=1)).isoformat()})
    with Session(engine) as session:
        results = purge_expired(session, build_storage(settings))
    category_name = mixed_world["category"]["name"]
    assert results[category_name]["finalists"] == 2
    assert coordinator.get(f"/api/v1/categories/{category_id}/finalists").json() == []

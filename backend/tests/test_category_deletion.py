"""Deleting a whole award category, such as a test category, from the command line."""

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app import cli
from app.config import get_settings
from app.main import app
from app.services.purge import delete_category
from app.services.storage import build_storage
from tests import test_reports
from tests.test_assessment import _approve_and_freeze
from tests.test_reports import generate

# Shared fixtures from the report tests.
world = test_reports.world
ranked = test_reports.ranked
_empty_queues = test_reports._empty_queues


def rows(engine: Engine, table: str, category_id: str) -> int:
    with engine.connect() as conn:
        return conn.execute(
            text(f"SELECT count(*) FROM {table} WHERE category_id = :c"),  # noqa: S608
            {"c": category_id},
        ).scalar_one()


def test_preview_then_delete_a_category(coordinator, ranked, engine, monkeypatch, capsys) -> None:
    category = ranked["category"]
    report = generate(coordinator, ranked, "individual", "Jane Doe").json()
    monkeypatch.setattr("app.cli.get_engine", lambda: engine)
    monkeypatch.setattr("app.cli.get_settings", app.dependency_overrides[get_settings])

    cli.delete_category(category["code"], confirmed=False)
    preview = capsys.readouterr().out
    assert "finalists: 2" in preview and "ranking_snapshots: 1" in preview
    assert "Nothing deleted" in preview
    assert coordinator.get(f"/api/v1/categories/{category['id']}").status_code == 200

    cli.delete_category(category["code"], confirmed=True)
    assert "Deleted Board Leadership Award: 2 finalist(s)" in capsys.readouterr().out
    assert coordinator.get(f"/api/v1/categories/{category['id']}").status_code == 404
    for table in ("rubric_versions", "assessment_runs", "ranking_snapshots", "reports"):
        assert rows(engine, table, category["id"]) == 0, table
    assert coordinator.get(f"/api/v1/reports/{report['id']}").status_code == 404
    with engine.connect() as conn:
        logged = conn.execute(
            text("SELECT details->>'code' FROM audit_events WHERE action = 'category.deleted'")
        ).scalars()
        assert category["code"] in logged

    with pytest.raises(SystemExit, match="No category with code"):
        cli.delete_category(category["code"], confirmed=True)


def test_protected_records_block_deletion(client_for, coordinator, world, engine) -> None:
    _approve_and_freeze(client_for, world)
    settings = app.dependency_overrides[get_settings]()
    with Session(engine) as session, pytest.raises(PermissionError, match="is frozen"):
        delete_category(session, build_storage(settings), world["category"]["id"], None, "test")
    # Nothing was removed.
    assert coordinator.get(f"/api/v1/categories/{world['category']['id']}/finalists").json()

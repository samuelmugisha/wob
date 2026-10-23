"""Database-level guarantees from the spec (§2, §5, §6, §7, §13)."""

import hashlib
import uuid

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError


def insert(conn: Connection, sql: str, **params) -> uuid.UUID:
    return conn.execute(text(sql), params).scalar_one()


def assert_rejected(conn: Connection, sql: str, match: str, **params) -> None:
    savepoint = conn.begin_nested()
    with pytest.raises(DBAPIError, match=match):
        conn.execute(text(sql), params)
    savepoint.rollback()


def make_user(conn: Connection) -> uuid.UUID:
    return insert(
        conn,
        "INSERT INTO users (email, display_name, role) VALUES (:email, 'Admin', 'admin') "
        "RETURNING id",
        email=f"{uuid.uuid4()}@example.org",
    )


def make_category(conn: Connection) -> uuid.UUID:
    return insert(
        conn,
        "INSERT INTO award_categories (code, name) VALUES (:code, 'Test category') RETURNING id",
        code=uuid.uuid4().hex,
    )


def make_finalist_category(conn: Connection, category_id: uuid.UUID) -> uuid.UUID:
    finalist_id = insert(
        conn, "INSERT INTO finalists (full_name) VALUES ('Test Finalist') RETURNING id"
    )
    return insert(
        conn,
        "INSERT INTO finalist_categories (finalist_id, category_id) VALUES (:f, :c) RETURNING id",
        f=finalist_id,
        c=category_id,
    )


def make_document(
    conn: Connection, finalist_category_id: uuid.UUID, confirmed_by: uuid.UUID | None
) -> uuid.UUID:
    return insert(
        conn,
        """
        INSERT INTO documents (finalist_category_id, mapping_confirmed_by, mapping_confirmed_at,
                               filename, storage_key, sha256_hash, mime_type, size_bytes)
        VALUES (:fc, :by, CASE WHEN CAST(:by AS uuid) IS NULL THEN NULL ELSE now() END,
                'nomination.pdf', :key, :sha, 'application/pdf', 1024)
        RETURNING id
        """,
        fc=finalist_category_id,
        by=confirmed_by,
        key=f"originals/{uuid.uuid4()}",
        sha=hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
    )


INSERT_CHUNK = """
    INSERT INTO document_chunks (document_id, finalist_category_id, chunk_index, content,
                                 extraction_version)
    VALUES (:doc, :fc, :idx, 'Chaired the audit committee from 2021 to 2024.', 'v1')
    RETURNING id
"""


@pytest.fixture
def world(conn: Connection) -> dict[str, uuid.UUID]:
    """Two finalists in one category, each with a confirmed document and one chunk."""
    admin = make_user(conn)
    category = make_category(conn)
    fc_a = make_finalist_category(conn, category)
    fc_b = make_finalist_category(conn, category)
    doc_a = make_document(conn, fc_a, confirmed_by=admin)
    doc_b = make_document(conn, fc_b, confirmed_by=admin)
    return {
        "admin": admin,
        "category": category,
        "fc_a": fc_a,
        "fc_b": fc_b,
        "doc_a": doc_a,
        "chunk_a": insert(conn, INSERT_CHUNK, doc=doc_a, fc=fc_a, idx=0),
        "chunk_b": insert(conn, INSERT_CHUNK, doc=doc_b, fc=fc_b, idx=0),
    }


def test_extensions_and_rating_scale(conn: Connection) -> None:
    extensions = set(conn.execute(text("SELECT extname FROM pg_extension")).scalars())
    assert {"vector", "pgcrypto"} <= extensions
    ratings = conn.execute(text("SELECT rating FROM rating_scale ORDER BY rating")).scalars()
    assert list(ratings) == [1, 2, 3, 4, 5]
    assert_rejected(conn, "DELETE FROM rating_scale WHERE rating = 1", "append-only")


def test_chunks_require_confirmed_mapping(conn: Connection) -> None:
    fc = make_finalist_category(conn, make_category(conn))
    unconfirmed = make_document(conn, fc, confirmed_by=None)
    assert_rejected(conn, INSERT_CHUNK, "administrator-confirmed", doc=unconfirmed, fc=fc, idx=0)


def test_chunk_finalist_must_match_document(conn: Connection, world) -> None:
    assert_rejected(conn, INSERT_CHUNK, "foreign key", doc=world["doc_a"], fc=world["fc_b"], idx=1)


def test_full_text_column_is_generated(conn: Connection, world) -> None:
    hit = conn.execute(
        text(
            "SELECT count(*) FROM document_chunks WHERE finalist_category_id = :fc "
            "AND content_tsv @@ plainto_tsquery('english', 'audit')"
        ),
        {"fc": world["fc_a"]},
    ).scalar_one()
    assert hit == 1


def test_claim_cannot_cite_another_finalists_evidence(conn: Connection, world) -> None:
    claim = insert(
        conn,
        "INSERT INTO claims (finalist_category_id, wording) VALUES (:fc, 'Chaired audit') "
        "RETURNING id",
        fc=world["fc_a"],
    )
    sql = """
        INSERT INTO claim_evidence (claim_id, finalist_category_id, chunk_id, relation, quoted_span)
        VALUES (:claim, :fc, :chunk, 'supports', 'Chaired the audit committee') RETURNING id
    """
    insert(conn, sql, claim=claim, fc=world["fc_a"], chunk=world["chunk_a"])
    assert_rejected(conn, sql, "foreign key", claim=claim, fc=world["fc_a"], chunk=world["chunk_b"])
    assert_rejected(conn, sql, "foreign key", claim=claim, fc=world["fc_b"], chunk=world["chunk_b"])


def make_assessment_context(
    conn: Connection, world, scale: str = "one_to_five"
) -> tuple[uuid.UUID, uuid.UUID]:
    rubric = insert(
        conn,
        "INSERT INTO rubric_versions (category_id, version, scale) VALUES (:c, 1, :s) RETURNING id",
        c=world["category"],
        s=scale,
    )
    criterion = insert(
        conn,
        "INSERT INTO rubric_criteria (rubric_version_id, code, name, description, position) "
        "VALUES (:r, 'leadership', 'Leadership', 'Board leadership', 1) RETURNING id",
        r=rubric,
    )
    run = insert(
        conn,
        """
        INSERT INTO assessment_runs (category_id, rubric_version_id, idempotency_key, llm_model,
                                     prompt_version, embedding_model)
        VALUES (:c, :r, :key, 'test-llm', 'assess-v1', 'test-embed') RETURNING id
        """,
        c=world["category"],
        r=rubric,
        key=uuid.uuid4().hex,
    )
    return run, criterion


@pytest.mark.parametrize(
    ("scale", "rating"), [("one_to_five", 0), ("one_to_five", 6), ("zero_to_three", 4)]
)
def test_ratings_outside_the_rubric_scale_rejected(
    conn: Connection, world, scale: str, rating: int
) -> None:
    run, criterion = make_assessment_context(conn, world, scale)
    assert_rejected(
        conn,
        """
        INSERT INTO criterion_assessments (run_id, finalist_category_id, criterion_id, rating,
                                           rationale, sufficiency)
        VALUES (:run, :fc, :crit, :rating, 'n/a', 'insufficient')
        """,
        "outside the rubric",
        run=run,
        fc=world["fc_a"],
        crit=criterion,
        rating=rating,
    )


def test_zero_is_a_rating_on_the_zero_to_three_scale(conn: Connection, world) -> None:
    run, criterion = make_assessment_context(conn, world, "zero_to_three")
    conn.execute(
        text(
            "INSERT INTO criterion_assessments (run_id, finalist_category_id, criterion_id, "
            "rating, rationale, sufficiency) VALUES (:run, :fc, :crit, 0, 'n/a', 'insufficient')"
        ),
        {"run": run, "fc": world["fc_a"], "crit": criterion},
    )
    new_version = conn.execute(
        text("INSERT INTO rubric_versions (category_id, version) VALUES (:c, 2) RETURNING scale"),
        {"c": world["category"]},
    ).scalar_one()
    assert new_version == "zero_to_three"  # the board's scale is the default for new versions


def test_citation_cannot_reference_another_finalist(conn: Connection, world) -> None:
    run, criterion = make_assessment_context(conn, world)
    assessment = insert(
        conn,
        """
        INSERT INTO criterion_assessments (run_id, finalist_category_id, criterion_id, rating,
                                           rationale, sufficiency)
        VALUES (:run, :fc, :crit, 4, 'Strong evidence of board leadership', 'sufficient')
        RETURNING id
        """,
        run=run,
        fc=world["fc_a"],
        crit=criterion,
    )
    assert_rejected(
        conn,
        """
        INSERT INTO assessment_citations (criterion_assessment_id, finalist_category_id, chunk_id,
                                          relation, quoted_span)
        VALUES (:a, :fc, :chunk, 'supports', 'Chaired the audit committee')
        """,
        "foreign key",
        a=assessment,
        fc=world["fc_a"],
        chunk=world["chunk_b"],
    )


def test_rubric_lifecycle(conn: Connection, world) -> None:
    category = world["category"]
    assert_rejected(
        conn,
        "INSERT INTO rubric_versions (category_id, version, status, approved_by, approved_at, "
        "frozen_at) VALUES (:c, 9, 'frozen', :u, now(), now())",
        "created as drafts",
        c=category,
        u=world["admin"],
    )

    rubric = insert(
        conn,
        "INSERT INTO rubric_versions (category_id, version, weighting) "
        "VALUES (:c, 1, 'weighted') RETURNING id",
        c=category,
    )
    freeze = (
        "UPDATE rubric_versions SET status = 'frozen', approved_by = :u, approved_at = now(), "
        "frozen_at = now() WHERE id = :r"
    )
    assert_rejected(conn, freeze, "has no criteria", u=world["admin"], r=rubric)

    add_criterion = (
        "INSERT INTO rubric_criteria (rubric_version_id, code, name, description, weight, position)"
        " VALUES (:r, :code, :code, 'Criterion', :w, :pos)"
    )
    conn.execute(text(add_criterion), {"r": rubric, "code": "impact", "w": None, "pos": 1})
    assert_rejected(conn, freeze, "without weights", u=world["admin"], r=rubric)

    conn.execute(
        text("UPDATE rubric_criteria SET weight = 2 WHERE rubric_version_id = :r"), {"r": rubric}
    )
    conn.execute(text(freeze), {"u": world["admin"], "r": rubric})

    assert_rejected(conn, add_criterion, "cannot change", r=rubric, code="extra", w=1, pos=2)
    assert_rejected(
        conn, "UPDATE rubric_versions SET notes = 'x' WHERE id = :r", "is frozen", r=rubric
    )

    # Only an administrator's request (wob.rubric_admin) may unfreeze, and only to approved.
    unfreeze = "UPDATE rubric_versions SET status = 'approved', frozen_at = NULL WHERE id = :r"
    assert_rejected(conn, unfreeze, "is frozen", r=rubric)
    conn.execute(text("SET LOCAL wob.rubric_admin = 'on'"))
    assert_rejected(
        conn,
        "UPDATE rubric_versions SET status = 'draft', approved_by = NULL, approved_at = NULL, "
        "frozen_at = NULL WHERE id = :r",
        "is frozen",
        r=rubric,
    )
    conn.execute(text(unfreeze), {"r": rubric})
    conn.execute(text(add_criterion), {"r": rubric, "code": "extra", "w": 1, "pos": 2})
    conn.execute(text("SET LOCAL wob.rubric_admin = 'off'"))
    assert_rejected(conn, add_criterion, "cannot change", r=rubric, code="more", w=1, pos=3)


def test_document_original_is_immutable(conn: Connection, world) -> None:
    assert_rejected(
        conn,
        "UPDATE documents SET sha256_hash = :sha WHERE id = :d",
        "immutable",
        sha="0" * 64,
        d=world["doc_a"],
    )
    assert_rejected(conn, "DELETE FROM documents WHERE id = :d", "append-only", d=world["doc_a"])
    conn.execute(
        text("UPDATE documents SET processing_status = 'indexed' WHERE id = :d"),
        {"d": world["doc_a"]},
    )


def test_audit_events_are_append_only(conn: Connection) -> None:
    event = insert(
        conn,
        "INSERT INTO audit_events (action, entity_type) VALUES ('test', 'system') RETURNING id",
    )
    assert_rejected(
        conn, "UPDATE audit_events SET action = 'x' WHERE id = :e", "append-only", e=event
    )
    assert_rejected(conn, "DELETE FROM audit_events WHERE id = :e", "append-only", e=event)
    assert_rejected(conn, "TRUNCATE audit_events", "append-only")


def test_incomplete_finalists_have_no_score(conn: Connection, world) -> None:
    run, _ = make_assessment_context(conn, world)
    snapshot = insert(
        conn,
        """
        INSERT INTO ranking_snapshots (category_id, run_id, rubric_version_id, weighting,
                                       calculation_version)
        SELECT :c, :run, rubric_version_id, 'equal', 'calc-v1' FROM assessment_runs WHERE id = :run
        RETURNING id
        """,
        c=world["category"],
        run=run,
    )
    entry = """
        INSERT INTO ranking_entries (snapshot_id, finalist_category_id, score, rank,
                                     criteria_assessed, criteria_total)
        VALUES (:s, :fc, :score, :rank, :assessed, 5)
    """
    assert_rejected(
        conn, entry, "check constraint", s=snapshot, fc=world["fc_a"], score=3.4, rank=1, assessed=4
    )
    conn.execute(
        text(entry),
        {"s": snapshot, "fc": world["fc_a"], "score": None, "rank": None, "assessed": 4},
    )
    assert_rejected(
        conn, "DELETE FROM ranking_entries WHERE snapshot_id = :s", "append-only", s=snapshot
    )

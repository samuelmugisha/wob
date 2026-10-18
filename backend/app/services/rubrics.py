"""Versioned rubrics (spec §7): drafts are editable; approved and frozen ones are not (the
database enforces this too). Production rankings need a frozen rubric."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import RubricCriterion, RubricStatus, RubricVersion, User, WeightingMode
from app.services import audit

TEMPLATE_NOTE = (
    "DRAFT TEMPLATE: illustrative criteria to exercise the system. They are not committee "
    "policy and must be replaced by the committee's approved criteria before any real ranking."
)

DRAFT_TEMPLATE: list[dict[str, Any]] = [
    {
        "code": "governance-leadership",
        "name": "Board leadership and governance",
        "description": "Leadership on boards or board committees: chairing, strategic "
        "oversight and governance improvements the nominee led.",
        "evidence_expectations": "Board and committee roles with dates; specific governance "
        "decisions or reforms the nominee led; board evaluation results.",
    },
    {
        "code": "measurable-impact",
        "name": "Measurable organisational impact",
        "description": "Results for the organisations the nominee serves that can be "
        "attributed to the nominee's board work.",
        "evidence_expectations": "Quantified outcomes with dates and sources, such as annual "
        "reports or audited figures; how the nominee contributed.",
    },
    {
        "code": "advancing-women",
        "name": "Advancing women in leadership",
        "description": "Mentoring, sponsorship and advocacy that increase women's "
        "representation and influence on boards.",
        "evidence_expectations": "Named programmes, numbers mentored or sponsored, resulting "
        "appointments, policies championed.",
    },
    {
        "code": "integrity-stewardship",
        "name": "Ethics, integrity and stewardship",
        "description": "Stewardship of risk, compliance, accountability and sustainability.",
        "evidence_expectations": "Audit, risk or ethics roles; policies introduced; "
        "regulatory or stakeholder outcomes.",
    },
    {
        "code": "recognition-influence",
        "name": "Recognition and sector influence",
        "description": "Recognition from credible bodies and influence on governance practice "
        "beyond the nominee's own boards. Not popularity or online following.",
        "evidence_expectations": "Awards with issuer and year; invited roles on standard-"
        "setting or professional bodies; published governance work.",
    },
]


class RubricError(ValueError):
    def __init__(self, message: str, *, conflict: bool = False) -> None:
        super().__init__(message)
        self.conflict = conflict


def _criteria(rubric: RubricVersion, items: list[dict[str, Any]]) -> list[RubricCriterion]:
    codes = [i["code"] for i in items]
    if not items:
        raise RubricError("a rubric needs at least one criterion")
    if len(set(codes)) != len(codes):
        raise RubricError("criterion codes must be unique")
    return [
        RubricCriterion(
            id=uuid.uuid4(),
            rubric_version_id=rubric.id,
            code=i["code"],
            name=i["name"],
            description=i["description"],
            evidence_expectations=i.get("evidence_expectations"),
            weight=Decimal(str(i["weight"])) if i.get("weight") is not None else None,
            position=n,
        )
        for n, i in enumerate(items, start=1)
    ]


def create_draft(
    session: Session,
    category_id: uuid.UUID,
    user: User,
    criteria: list[dict[str, Any]],
    *,
    weighting: WeightingMode = WeightingMode.EQUAL,
    notes: str | None = None,
) -> RubricVersion:
    version = (
        session.scalar(
            select(func.max(RubricVersion.version)).where(RubricVersion.category_id == category_id)
        )
        or 0
    ) + 1
    rubric = RubricVersion(
        id=uuid.uuid4(), category_id=category_id, version=version, weighting=weighting, notes=notes
    )
    session.add(rubric)
    session.flush()
    session.add_all(_criteria(rubric, criteria))
    audit.record(
        session,
        user,
        "rubric.created",
        "rubric_version",
        rubric.id,
        version=version,
        criteria=[c["code"] for c in criteria],
    )
    return rubric


def update_draft(
    session: Session,
    rubric: RubricVersion,
    user: User,
    criteria: list[dict[str, Any]],
    *,
    weighting: WeightingMode,
    notes: str | None,
) -> None:
    if rubric.status != RubricStatus.DRAFT:
        raise RubricError(
            f"rubric version {rubric.version} is {rubric.status.value}; "
            "create a new version to change it",
            conflict=True,
        )
    session.execute(delete(RubricCriterion).where(RubricCriterion.rubric_version_id == rubric.id))
    session.flush()
    rubric.weighting = weighting
    rubric.notes = notes
    session.add_all(_criteria(rubric, criteria))
    audit.record(
        session,
        user,
        "rubric.updated",
        "rubric_version",
        rubric.id,
        criteria=[c["code"] for c in criteria],
        weighting=weighting.value,
    )
    session.flush()
    session.expire(rubric, ["criteria"])


def approve(session: Session, rubric: RubricVersion, user: User) -> None:
    if rubric.status != RubricStatus.DRAFT:
        raise RubricError(f"rubric is already {rubric.status.value}", conflict=True)
    if rubric.weighting == WeightingMode.WEIGHTED and any(
        c.weight is None for c in rubric.criteria
    ):
        raise RubricError("every criterion needs a weight for weighted scoring")
    rubric.status = RubricStatus.APPROVED
    rubric.approved_by = user.id
    rubric.approved_at = datetime.now(UTC)
    audit.record(session, user, "rubric.approved", "rubric_version", rubric.id)


def freeze(session: Session, rubric: RubricVersion, user: User) -> None:
    if rubric.status != RubricStatus.APPROVED:
        raise RubricError("only an approved rubric can be frozen", conflict=True)
    rubric.status = RubricStatus.FROZEN
    rubric.frozen_at = datetime.now(UTC)
    audit.record(session, user, "rubric.frozen", "rubric_version", rubric.id)


def current_rubric(session: Session, category_id: uuid.UUID) -> RubricVersion | None:
    """The rubric assessments use: the latest frozen version, else the latest of any status."""
    rubrics = session.scalars(
        select(RubricVersion)
        .where(RubricVersion.category_id == category_id)
        .order_by(RubricVersion.version.desc())
    ).all()
    frozen = [r for r in rubrics if r.status == RubricStatus.FROZEN]
    return frozen[0] if frozen else (rubrics[0] if rubrics else None)

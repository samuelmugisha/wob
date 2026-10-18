"""Finalist consent records (Act s.7, s.9(3)(b), s.19; Reg 30) and the checks that use them.

Part A (assessment) is required before evidence is uploaded when UPLOAD_REQUIRES_CONSENT is
on; otherwise only an explicit withdrawal of part A blocks uploads. Part B (AI processing abroad) is
required for claim extraction and AI assessment. Part C (public-source research) is required
for web research. A finalist who declines B or C is assessed by people only.
"""

import uuid
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FinalistConsent, User
from app.services import audit


class Purpose(StrEnum):
    ASSESSMENT = "assessment"
    AI_PROCESSING = "ai_processing"
    WEB_RESEARCH = "web_research"


MESSAGES = {
    Purpose.ASSESSMENT: "record the finalist's consent to assessment (part A) before adding "
    "their evidence",
    Purpose.AI_PROCESSING: "the finalist has not consented to AI-assisted processing abroad "
    "(part B); assess them by human review instead",
    Purpose.WEB_RESEARCH: "the finalist has not consented to public-source research (part C)",
}


class ConsentMissing(PermissionError):
    def __init__(self, purpose: Purpose) -> None:
        super().__init__(MESSAGES[purpose])
        self.purpose = purpose


def current(session: Session, finalist_category_id: uuid.UUID) -> FinalistConsent | None:
    return session.scalar(
        select(FinalistConsent)
        .where(FinalistConsent.finalist_category_id == finalist_category_id)
        .order_by(FinalistConsent.recorded_at.desc(), FinalistConsent.id.desc())
        .limit(1)
    )


def has(session: Session, finalist_category_id: uuid.UUID, purpose: Purpose) -> bool:
    record = current(session, finalist_category_id)
    return bool(record and getattr(record, purpose.value))


def withdrawn(session: Session, finalist_category_id: uuid.UUID, purpose: Purpose) -> bool:
    """True when consent was recorded and later withdrawn (the latest record says no)."""
    record = current(session, finalist_category_id)
    return record is not None and not getattr(record, purpose.value)


def require(session: Session, finalist_category_id: uuid.UUID, purpose: Purpose) -> None:
    if not has(session, finalist_category_id, purpose):
        raise ConsentMissing(purpose)


def record(
    session: Session,
    finalist_category_id: uuid.UUID,
    user: User,
    *,
    notice_version: str,
    assessment: bool,
    ai_processing: bool,
    web_research: bool,
    method: str,
    reference: str | None,
) -> FinalistConsent:
    if not assessment and (ai_processing or web_research):
        raise ValueError("AI processing and research consents need assessment consent too")
    consent = FinalistConsent(
        finalist_category_id=finalist_category_id,
        notice_version=notice_version,
        assessment=assessment,
        ai_processing=ai_processing,
        web_research=web_research,
        method=method,
        reference=reference,
        recorded_by=user.id,
    )
    session.add(consent)
    audit.record(
        session,
        user,
        "consent.recorded",
        "finalist_category",
        finalist_category_id,
        notice_version=notice_version,
        assessment=assessment,
        ai_processing=ai_processing,
        web_research=web_research,
        method=method,
    )
    return consent

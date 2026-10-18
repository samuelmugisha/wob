import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditEvent, User


def record(
    session: Session,
    actor: User | None,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None,
    **details: Any,
) -> None:
    session.add(
        AuditEvent(
            actor_id=actor.id if actor else None,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details,
        )
    )

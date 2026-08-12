"""The Satchel charter + consent record — single source of truth.

Satchel is the system's read-only courier: he runs bounded errands
against PUBLIC sources (the web-check and org-scout lanes) and brings
back proposals. Before he runs the first time, the teammate must accept
his operating charter; acceptance is recorded as an audit row and every
run is gated on it (guardrail P-10).

Keep the charter terse and human-readable — it is shown verbatim to the
teammate in chat before Satchel ever runs.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog, User
from app.services.audit import write_audit_row

CHARTER_ACK_ACTION = "satchel_charter_acknowledged"

# The non-negotiable operating constraints a teammate approves before
# Satchel ever runs. Single source of truth for the consent flow.
SATCHEL_CHARTER: list[str] = [
    "Read-only errands: Satchel fetches from public sources — he never "
    "writes to any outside system.",
    "Fetch-and-forget: he brings PROPOSALS with their sources for your "
    "review, then keeps nothing he saw.",
    "Encrypted the whole time he holds data; never written to disk in "
    "the clear.",
    "You decide: nothing enters the CRM without a human approving it, "
    "item by item.",
    "One-way handoff: once in the CRM, the privacy model (visibility "
    "tiers, redaction, owner-scoping, audit) governs the data.",
    "Every run is audited (who/when/how many searches) — never the "
    "content he forgot.",
]


def latest_ack(db: Session, user: User) -> AuditLog | None:
    """Newest charter-acknowledgment audit row for this teammate, if any."""
    return db.scalars(
        select(AuditLog)
        .where(
            AuditLog.user_id == user.id,
            AuditLog.action == CHARTER_ACK_ACTION,
        )
        .order_by(AuditLog.id.desc())
    ).first()


def is_acknowledged(db: Session, user: User) -> bool:
    """True once the teammate has accepted the Satchel charter."""
    return latest_ack(db, user) is not None


def record_acknowledgment(db: Session, user: User) -> None:
    """Record that the teammate accepted the charter (audit row, no data)."""
    write_audit_row(
        db,
        user,
        action=CHARTER_ACK_ACTION,
        target_type="user",
        target_id=user.id,
        payload_hash=None,
    )

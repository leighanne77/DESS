"""Events catalog service — catalog numbers and the Invited/Attended tie.

Owner ask 2026-08-11. Mirrors app/services/demand_signals.py: thin,
ORM-only, idempotent where it writes.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Event, EventContact

STATUS_INVITED = "Invited"
STATUS_ATTENDED = "Attended"


def next_catalog_number(db: Session, event_year: int) -> str:
    """DIN-<year>-<seq>, sequence per year, deleted events still counted
    (their numbers stay burned — a catalog number is forever)."""
    prefix = f"DIN-{event_year}-"
    count = db.scalar(
        select(func.count())
        .select_from(Event)
        .where(Event.catalog_number.like(f"{prefix}%"))
    )
    return f"{prefix}{(count or 0) + 1:03d}"


def create_event(
    db: Session,
    *,
    title: str,
    created_by_id: int,
    event_date: date | None = None,
    location: str | None = None,
    notes: str | None = None,
) -> Event:
    year = event_date.year if event_date else datetime.now(timezone.utc).year
    event = Event(
        catalog_number=next_catalog_number(db, year),
        title=title,
        event_date=event_date,
        location=location,
        notes=notes,
        created_by_id=created_by_id,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def find_event(db: Session, ref: str) -> Event | None:
    """Resolve a user's reference — exact catalog number first, else a
    case-insensitive title substring (unique match only)."""
    ref = ref.strip()
    event = db.scalars(
        select(Event).where(
            func.lower(Event.catalog_number) == ref.lower(),
            Event.deleted_at.is_(None),
        )
    ).first()
    if event is not None:
        return event
    matches = list(
        db.scalars(
            select(Event)
            .where(Event.title.ilike(f"%{ref}%"), Event.deleted_at.is_(None))
            .limit(2)
        )
    )
    return matches[0] if len(matches) == 1 else None


def record_invite(
    db: Session,
    *,
    event_id: int,
    contact_id: int,
    status: str,
    created_by_id: int,
    note: str | None = None,
) -> EventContact:
    """Idempotent upsert of the (event, contact) tie.

    Status only moves FORWARD: Attended upgrades Invited in place;
    recording Invited on someone already Attended is a no-op (they were
    necessarily invited). A soft-deleted tie is revived.
    """
    row = db.scalars(
        select(EventContact).where(
            EventContact.event_id == event_id,
            EventContact.contact_id == contact_id,
        )
    ).first()
    if row is None:
        row = EventContact(
            event_id=event_id,
            contact_id=contact_id,
            status=status,
            created_by_id=created_by_id,
            note=note,
        )
        db.add(row)
    else:
        row.deleted_at = None
        if status == STATUS_ATTENDED:
            row.status = STATUS_ATTENDED
        # Invited never downgrades Attended.
        if note is not None:
            row.note = note
    db.commit()
    db.refresh(row)
    return row

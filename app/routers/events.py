"""Events REST endpoints — the card's view of a contact's event history.

The chat tools (create_event / record_event_invite) are the primary
write surface; these exist so the expanded contact card can show which
events a person was invited to, whether they attended, and the per-tie
note — and record/annotate without a chat round-trip. Both surfaces run
the same service, so they audit identically.
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import Contact, Event, EventContact, User
from app.services import events as svc
from app.services.audit import write_audit_row
from app.services.privacy import visible_contacts_query

router = APIRouter(tags=["events"], dependencies=[Depends(get_current_user)])


class ContactEventRead(BaseModel):
    event_id: int
    catalog_number: str
    title: str
    event_date: str | None
    status: str
    note: str | None


def _visible_or_404(contact_id: int, db: Session, user: User) -> Contact:
    contact = db.scalars(
        visible_contacts_query(user).where(Contact.id == contact_id)
    ).first()
    if contact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return contact


@router.get("/contacts/{contact_id}/events", response_model=list[ContactEventRead])
def events_for_contact(
    contact_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ContactEventRead]:
    """This contact's event history — 404 on invisible contacts, same
    privacy stance as the demand-signals twin."""
    _visible_or_404(contact_id, db, current_user)
    rows = list(
        db.execute(
            select(EventContact, Event)
            .join(Event, Event.id == EventContact.event_id)
            .where(
                EventContact.contact_id == contact_id,
                EventContact.deleted_at.is_(None),
                Event.deleted_at.is_(None),
            )
            .order_by(Event.catalog_number.desc())
        )
    )
    return [
        ContactEventRead(
            event_id=e.id,
            catalog_number=e.catalog_number,
            title=e.title,
            event_date=str(e.event_date) if e.event_date else None,
            status=tie.status,
            note=tie.note,
        )
        for tie, e in rows
    ]


class RecordTieRequest(BaseModel):
    event: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Catalog number or unique title fragment.",
    )
    status: Literal["Invited", "Attended"] = "Invited"
    note: str | None = Field(None, max_length=2000)


@router.post("/contacts/{contact_id}/events", response_model=ContactEventRead)
def record_contact_event(
    contact_id: int,
    payload: RecordTieRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ContactEventRead:
    """Tie/annotate from the card — same forward-only status rule and
    note-update semantics as the chat tool."""
    contact = _visible_or_404(contact_id, db, current_user)
    event = svc.find_event(db, payload.event)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No single event matches '{payload.event}'.",
        )
    tie = svc.record_invite(
        db,
        event_id=event.id,
        contact_id=contact.id,
        status=payload.status,
        created_by_id=current_user.id,
        note=payload.note,
    )
    write_audit_row(
        db,
        current_user,
        action="record_event_invite",
        target_type="contact",
        target_id=contact.id,
        payload_hash=None,
        payload_metadata={
            "catalog_number": event.catalog_number,
            "status": tie.status,
            "via": "card",
        },
    )
    return ContactEventRead(
        event_id=event.id,
        catalog_number=event.catalog_number,
        title=event.title,
        event_date=str(event.event_date) if event.event_date else None,
        status=tie.status,
        note=tie.note,
    )

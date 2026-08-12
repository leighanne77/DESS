"""Contact CRUD endpoints.

Reads go through visible_contacts_query so private contacts stay private.
Writes (PATCH/DELETE/share) require ownership — we return 404 when the
contact isn't visible at all (don't reveal existence) and 403 when it's
visible but the caller doesn't own it.
"""

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import AuditLog, ChangeRequest, Contact, User
from app.schemas import ContactCreate, ContactRead, ContactShare, ContactUpdate
from app.services.audit import audit_log
from app.services.privacy import redactable_contacts_query, visible_contacts_query
from app.services.tool_dispatch import ALLOWED_REVEAL_FIELDS, DEFAULT_REVEAL_FIELDS
from app.services.user_link import user_id_for_email

router = APIRouter(
    prefix="/contacts",
    tags=["contacts"],
    dependencies=[Depends(get_current_user)],
)


def _load_visible_contact(contact_id: int, db: Session, current_user: User) -> Contact:
    """Return the contact if visible to current_user, else 404."""
    stmt = visible_contacts_query(current_user).where(Contact.id == contact_id)
    contact = db.scalars(stmt).first()
    if contact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return contact


def _require_owner(contact: Contact, current_user: User) -> None:
    """Raise 403 if the current user does not own the contact."""
    if contact.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)


@router.get("", response_model=list[ContactRead])
def list_contacts(
    include_retired: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Contact]:
    """Return contacts visible to the current user. Retired contacts are
    excluded unless ?include_retired=true — the list is a browse, not an
    explicit ask."""
    stmt = visible_contacts_query(current_user)
    if not include_retired:
        stmt = stmt.where(Contact.retired.is_(False))
    return list(db.scalars(stmt).all())


@router.get("/{contact_id}", response_model=ContactRead)
def get_contact(
    contact_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Contact:
    # Fetching someone by id IS the explicit ask, so retired contacts
    # come back here — the "mostly hidden" posture applies to searches.
    return _load_visible_contact(contact_id, db, current_user)


@router.post("", response_model=ContactRead, status_code=status.HTTP_201_CREATED)
@audit_log(action="create_contact", target_type="contact")
def create_contact(
    payload: ContactCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Contact:
    contact = Contact(**payload.model_dump(), owner_id=current_user.id)
    # Auto-link to the team user this contact *is*, by email match (see
    # user_link.py) — feeds the warm-intro engine's per-user scoping.
    contact.user_id = user_id_for_email(db, contact.email)
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact


@router.patch("/{contact_id}", response_model=ContactRead)
@audit_log(action="update_contact", target_type="contact", target_id_kwarg="contact_id")
def update_contact(
    contact_id: int,
    payload: ContactUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Contact:
    contact = _load_visible_contact(contact_id, db, current_user)
    _require_owner(contact, current_user)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(contact, field, value)
    db.commit()
    db.refresh(contact)
    return contact


@router.delete("/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
@audit_log(
    action="delete_contact",
    target_type="contact",
    target_id_kwarg="contact_id",
    payload_kwarg=None,
)
def delete_contact(
    contact_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    contact = _load_visible_contact(contact_id, db, current_user)
    _require_owner(contact, current_user)
    contact.deleted_at = datetime.now(timezone.utc)
    db.commit()


@router.post("/{contact_id}/share", response_model=ContactRead)
@audit_log(action="share_contact", target_type="contact", target_id_kwarg="contact_id")
def share_contact(
    contact_id: int,
    payload: ContactShare,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Contact:
    contact = _load_visible_contact(contact_id, db, current_user)
    _require_owner(contact, current_user)
    target = db.get(User, payload.user_id)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Target user not found"
        )
    if payload.user_id not in contact.shared_with:
        contact.shared_with = [*contact.shared_with, payload.user_id]
        db.commit()
        db.refresh(contact)
    return contact


# Phase 2 Slice 6.8 — change log endpoint.
# Surfaces audit_log rows tied to one contact, with the actor's display
# name + a human-readable action label so the frontend's expanded card
# can render a history pane without doing JOIN gymnastics. Privacy: the
# requester must be able to SEE the contact (visible OR redacted view).
# For redacted callers we still expose the changelog (when actions
# happened + who did them) but never the contact's full identity —
# that's already gated by the redacted view in search results.

# Friendly action -> verb-phrase mapping. Anything not in the map is
# rendered as the raw action string. `redacted_reveal` (a READ, not a
# WRITE) is intentionally filtered out — see the endpoint body.
_ACTION_LABELS: dict[str, str] = {
    "create_contact": "created the contact",
    "update_contact": "updated the contact",
    "delete_contact": "deleted the contact",
    "transfer_contact": "transferred ownership",
    "share_contact": "shared the contact with a teammate",
    "request_change": "filed a change request",
    "resolve_change_request": "resolved a change request",
}


class ChangelogEntry(BaseModel):
    """One row in a contact's change history."""

    id: int
    when: datetime
    actor_id: int
    actor_name: str | None
    action: str
    action_label: str
    # Slice 6.9 — action-specific structured payload (shape varies by
    # action; see AuditLog.payload_metadata docstring). For redacted-
    # view callers, any `changes` entries whose `field` is not in the
    # contact's reveal_fields are stripped here before serving — that's
    # the privacy gate.
    metadata: dict[str, Any] | None = None


def _filter_changes_for_reveal(
    metadata: dict[str, Any] | None, reveal: set[str]
) -> dict[str, Any] | None:
    """Privacy gate for redacted-view callers. Strip any `changes`
    entries whose `field` isn't in the caller's reveal set — that
    prevents the changelog from becoming a side-channel that leaks the
    old/new values of hidden fields (e.g. notes, email, phones).

    Returns the metadata with `changes` filtered, or None if no
    safe-to-show fields remain (the row is still shown but as a
    generic 'updated the contact' with no diff)."""
    if not metadata or "changes" not in metadata:
        return metadata
    filtered = [c for c in metadata.get("changes", []) if c.get("field") in reveal]
    return {**metadata, "changes": filtered}


@router.get("/{contact_id}/changelog", response_model=list[ChangelogEntry])
def contact_changelog(
    contact_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ChangelogEntry]:
    """Return the contact's change history, newest first.

    Authorization: the requester must be able to see the contact in
    some form (full or redacted). Returns 404 if it's a fully-hidden
    private contact owned by someone who disabled existence hints.

    Audit rows pulled by union:
      - direct: target_type=contact, target_id=contact_id (create,
        update, delete, transfer)
      - indirect: target_type=change_request, joined via
        change_requests.contact_id (request_change, resolve_change_request)

    `redacted_reveal` rows are excluded — those are READS, not changes.

    Privacy gate: for redacted callers we serve the audit timeline but
    strip `changes` entries whose field is not in the contact's
    reveal_fields. That keeps the timeline useful ("Jordan Blake updated
    the contact on May 14") without leaking hidden-field before/after
    values.
    """
    visible = db.scalars(
        visible_contacts_query(current_user).where(Contact.id == contact_id)
    ).first()
    redactable: Contact | None = None
    if visible is None:
        redactable = db.scalars(
            redactable_contacts_query(current_user).where(Contact.id == contact_id)
        ).first()
    if visible is None and redactable is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    contact = visible or redactable
    assert contact is not None  # narrowing for type-checker

    # Direct rows: target_type=contact.
    direct_rows = list(
        db.scalars(
            select(AuditLog)
            .where(
                AuditLog.target_type == "contact",
                AuditLog.target_id == contact_id,
                AuditLog.action != "redacted_reveal",
            )
            .order_by(AuditLog.created_at.desc())
            .limit(200)
        )
    )

    # Indirect rows: target_type=change_request whose contact_id ties back.
    indirect_rows = list(
        db.scalars(
            select(AuditLog)
            .join(ChangeRequest, ChangeRequest.id == AuditLog.target_id)
            .where(
                AuditLog.target_type == "change_request",
                ChangeRequest.contact_id == contact_id,
            )
            .order_by(AuditLog.created_at.desc())
            .limit(200)
        )
    )

    # Merge, sort newest first, cap.
    rows = sorted(
        direct_rows + indirect_rows, key=lambda r: r.created_at, reverse=True
    )[:200]

    actor_ids = {r.user_id for r in rows}
    actors_by_id: dict[int, str | None] = {}
    if actor_ids:
        users = list(db.scalars(select(User).where(User.id.in_(actor_ids))))
        actors_by_id = {u.id: u.name for u in users}

    # Redacted callers get a reduced diff view. Owner/sharee callers
    # (full visibility) see every field.
    is_redacted_view = visible is None
    if is_redacted_view:
        reveal = (
            set(contact.reveal_fields or DEFAULT_REVEAL_FIELDS) & ALLOWED_REVEAL_FIELDS
        )
    else:
        # Owner/sharee — allow every field through; this superset
        # of ALLOWED_REVEAL_FIELDS effectively disables the gate.
        reveal = ALLOWED_REVEAL_FIELDS | {
            "notes",
            "email",
            "cell_phone",
            "office_phone",
            "title",
            "image_url",
            "patina_overrides",
            "reveal_fields",
        }

    return [
        ChangelogEntry(
            id=row.id,
            when=row.created_at,
            actor_id=row.user_id,
            actor_name=actors_by_id.get(row.user_id),
            action=row.action,
            action_label=_ACTION_LABELS.get(row.action, row.action),
            metadata=_filter_changes_for_reveal(row.payload_metadata, reveal),
        )
        for row in rows
    ]

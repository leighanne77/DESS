"""Event + EventContact models — the events catalog (owner ask 2026-08-11).

An **Event** is a DIN gathering — a dinner, a demo day, a delegation —
catalogued under a stable, human-readable **catalog number**
(``DIN-2026-001``): the number is how the team refers to the event in
conversation and how a contact's history ties back to it.

**event_contacts** is the join: one row per (event, contact) carrying a
``status`` of ``Invited`` or ``Attended``. Attended supersedes Invited —
recording attendance UPGRADES the existing row, never duplicates it — so
"invited but never came" is precisely the rows still sitting at
``Invited``. Idempotent-upsert like ``demand_signal_contacts``.

Events are team-shared (like demand signals): any teammate can see and
record against any event. The CONTACT side keeps its privacy rules — you
can only tie people you can see.
"""

from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Event(Base):
    """A catalogued DIN event."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)

    # The stable public handle, e.g. "DIN-2026-001" — assigned at create
    # (year of the event date, else the current year, plus a sequence).
    # Unique forever; renaming an event never changes its number.
    catalog_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)

    # Short label the team scans by, e.g. "Mobile Defense Dinner".
    title: Mapped[str] = mapped_column(String(255), nullable=False)

    # When and where — both optional: an event can be catalogued before
    # it is scheduled.
    event_date: Mapped[date | None] = mapped_column(Date)
    location: Mapped[str | None] = mapped_column(String(255))

    notes: Mapped[str | None] = mapped_column(Text)

    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    # Soft delete, house style: it disappears from reads, the catalog
    # number stays burned (unique across live AND deleted).
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class EventContact(Base):
    """A person tied to an event: Invited, or Invited-and-Attended.

    One row per (event, contact). ``status`` only moves forward —
    recording "Attended" upgrades an "Invited" row in place; recording
    "Invited" for someone already marked Attended is a no-op (they were
    necessarily invited). See app/services/events.record_invite.
    """

    __tablename__ = "event_contacts"
    __table_args__ = (
        UniqueConstraint("event_id", "contact_id", name="uq_event_contact"),
        Index("ix_event_contacts_event_live", "event_id", "deleted_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), nullable=False)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), nullable=False)

    # "Invited" | "Attended" — validated at the tool boundary.
    status: Mapped[str] = mapped_column(
        String(10), default="Invited", server_default="Invited", nullable=False
    )

    # Free-text event note for THIS person on THIS event — "brought two
    # colleagues", "asked for the deck". Editable from the card and by
    # voice; updated in place on re-record.
    note: Mapped[str | None] = mapped_column(Text)

    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

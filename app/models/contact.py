"""Contact model — Phase 1 simplified schema.

Uses company_name VARCHAR directly instead of a companies FK for MVP simplicity.
A companies table can be introduced in Phase 2 once data volume justifies it.
"""

from datetime import datetime

from sqlalchemy import ARRAY, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Contact(Base):
    """A person in DIN's network — LP, portfolio target, advisor, etc."""

    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255))
    cell_phone: Mapped[str | None] = mapped_column(String(20))
    office_phone: Mapped[str | None] = mapped_column(String(20))
    title: Mapped[str | None] = mapped_column(String(255))
    company_name: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)

    # Ownership & privacy
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    # Default PRIVATE: any write path that doesn't explicitly answer the
    # "share with the team" question produces an owner-only contact —
    # sharing is always an explicit choice.
    is_private: Mapped[bool] = mapped_column(Boolean, default=True)
    shared_with: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), default=list, server_default="{}"
    )
    # Phase 2 Slice 6.5 — partial-reveal privacy.
    # When is_private=True and the caller is NOT the owner, reveal_fields
    # controls which columns are visible to teammates. Everything else
    # (name, email, phones, notes, title, image_url) is redacted to
    # "Private contact" / null. The owner edits this per contact; the
    # default set is the safe metadata that helps teammates know "a
    # teammate has someone in X fund at Y company" without exposing PII.
    # Public contacts (is_private=False) ignore this column entirely.
    # NOT NULL at the DB level after migration 11935709768a — server
    # default is the safe metadata set. Code still defends with a
    # fallback constant so a missing value never leaks more than
    # intended (belt + suspenders).
    reveal_fields: Mapped[list[str]] = mapped_column(
        ARRAY(String(50)),
        nullable=False,
        default=lambda: ["primary_fund", "company_name", "sectors"],
        server_default="{primary_fund,company_name,sectors}",
    )

    # Link to the team user this contact record *is*, when the contact is
    # a teammate (Alex Rivera / Sam Chen / Jordan Blake). Nullable — most
    # contacts aren't teammates. Auto-set by email-match on create
    # (app/services/user_link.py) + a one-time backfill in migration
    # d5b3f8a1c920. Lets the warm-intro engine start paths from the
    # requester's own contact node (their relationships) and never route
    # an intro through or to themselves. ondelete=SET NULL so removing a
    # user never deletes their contact card.
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # DIN-specific classification
    primary_fund: Mapped[str] = mapped_column(String(50), default="General")
    contact_type: Mapped[str] = mapped_column(String(50), default="Other")
    sectors: Mapped[list[str]] = mapped_column(
        ARRAY(String(100)), default=list, server_default="{}"
    )

    # Gender — used for pronouns in voice mode and for filtered reporting
    # ("show me women in Maritime"). Default Unknown so legacy rows are
    # safe and the field is genuinely optional on input.
    gender: Mapped[str] = mapped_column(
        String(20), default="Unknown", server_default="Unknown"
    )

    # Country (canonical full name, e.g. "United States", "Saudi Arabia",
    # "Canada"). Free text — Claude normalizes voice forms to canonical.
    country: Mapped[str | None] = mapped_column(String(100))

    # Metro / city the contact lives or operates in (e.g. "Mobile",
    # "Washington DC", "Houston"). Free text — Claude normalizes voice
    # forms. Finer-grained than country; used by the warm-introduction
    # engine's geography signal (same-metro = warmer connection). Nullable.
    metro: Mapped[str | None] = mapped_column(String(100))

    # LP subtype — only meaningful when contact_type == "LP". Lets us
    # filter "show me sovereign wealth fund contacts" without overloading
    # company_name. Nullable for non-LPs.
    lp_subtype: Mapped[str | None] = mapped_column(String(50))

    # Current government employee. Drives the 3-side fund-colored border
    # treatment on the contact card per §15.3.x. Auto-set on
    # create/update when email matches a known gov suffix
    # (see app.services.gov_detect); owner can toggle off for edge
    # cases like contractors with a .gov inbox. Distinct from
    # ex_government — that tracks history; this gates the border.
    is_gov_employee: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )

    # Fly status — required on input. "Must Fly" = work with them if at
    # all possible. "Fly List" = safe to work with if required. "Maybe
    # Must Fly" = under review (dotted plane). "Unknown" = haven't
    # decided yet, default for new contacts (no plane shown). "Off Fly
    # List" = ripped channels, no plane. Server default backfills
    # pre-rule rows.
    fly_status: Mapped[str] = mapped_column(
        String(20), default="Unknown", server_default="Unknown"
    )

    # Outreach consent for the warm-introduction engine (Phase 5).
    # Gates whether this contact may be offered as a node on an intro
    # path: only "APPROVED" contacts surface as intermediaries; "PENDING"
    # (default) and "DENIED" are never offered. Owner-only to change —
    # the normal update path is already owner-gated + audited. New rows
    # and every pre-Phase-5 contact backfill to "PENDING", so nobody is
    # routed to until a human explicitly approves them. Values:
    # APPROVED / PENDING / DENIED.
    opt_in_status: Mapped[str] = mapped_column(
        String(20), default="PENDING", server_default="PENDING", nullable=False
    )

    # Retired — kept in the CRM, mostly hidden (owner decision 2026-08-11).
    # Archiving without deleting: a retired contact drops out of searches,
    # pipeline summaries, and intro paths UNLESS the user explicitly asks
    # for retired people. Deliberately a flag, not a fly_status value or a
    # soft delete: fly status is about willingness to work with someone,
    # deletion is about the record not existing — retirement is neither.
    retired: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )

    # Headshot URL — strictly optional. When None the card shows nothing
    # in the headshot slot (no stand-in placeholder). When set, expected
    # to be a CDN-hosted square image; the frontend renders it at 56px.
    image_url: Mapped[str | None] = mapped_column(String(500))

    # Ex-government background. Useful filter for "show me ex-gov
    # contacts." Three values: Yes / No / Don't Know (default).
    ex_government: Mapped[str] = mapped_column(
        String(20), default="Don't Know", server_default="Don't Know"
    )

    # Patina overrides — user-set rolodex marks (stickers, doodles, etc).
    # NULL  = use deterministic auto-pick (default)
    # []    = explicit "no patina on this card"
    # [{}+] = up to 3 explicit patina items, validated by the Pydantic
    #         PatinaItem discriminated union at the API boundary.
    # Storage is JSONB so we can later index nested keys if reporting
    # ever needs it ("show me all contacts with a smiley sticker").
    patina_overrides: Mapped[list | None] = mapped_column(JSONB)

    # Timestamps + soft delete
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

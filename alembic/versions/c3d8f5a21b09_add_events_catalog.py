"""Add events + event_contacts — the events catalog.

Owner ask 2026-08-11: catalogue DIN events under stable catalog numbers
(DIN-2026-001) and tie contacts to them with a status of Invited or
Attended — attended supersedes invited, one row per (event, contact),
so "invited but never came" is the rows still at Invited.

Revision ID: c3d8f5a21b09
Revises: 9f4c1e2ab7d3
Create Date: 2026-08-11
"""

import sqlalchemy as sa

from alembic import op

revision = "c3d8f5a21b09"
down_revision = "9f4c1e2ab7d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("catalog_number", sa.String(20), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=True),
        sa.Column("location", sa.String(255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("catalog_number", name="uq_events_catalog_number"),
    )
    op.create_table(
        "event_contacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False),
        sa.Column(
            "contact_id", sa.Integer(), sa.ForeignKey("contacts.id"), nullable=False
        ),
        sa.Column(
            "status",
            sa.String(10),
            server_default="Invited",
            nullable=False,
        ),
        sa.Column(
            "created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("event_id", "contact_id", name="uq_event_contact"),
    )
    op.create_index(
        "ix_event_contacts_event_live",
        "event_contacts",
        ["event_id", "deleted_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_event_contacts_event_live", table_name="event_contacts")
    op.drop_table("event_contacts")
    op.drop_table("events")

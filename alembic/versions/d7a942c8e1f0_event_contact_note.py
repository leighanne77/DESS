"""event_contacts.note — a space for event notes on each tie.

Owner ask 2026-08-11 (same evening as the catalog itself): the card
shows what a contact was invited to and whether they came; the note is
where "brought two colleagues, asked for the deck" lives.

Revision ID: d7a942c8e1f0
Revises: c3d8f5a21b09
Create Date: 2026-08-11
"""

import sqlalchemy as sa

from alembic import op

revision = "d7a942c8e1f0"
down_revision = "c3d8f5a21b09"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("event_contacts", sa.Column("note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("event_contacts", "note")

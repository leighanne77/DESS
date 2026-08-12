"""Add contacts.retired — kept in the CRM, mostly hidden.

Retirement is archiving without deleting. A retired contact drops out
of searches, pipeline summaries, and intro paths unless retired people
are explicitly asked for. A flag rather than a fly_status value (that
axis is willingness-to-work-with) or a soft delete (the record still
exists and is reachable on request).

Server default false backfills every existing row: nobody is retired
until a human says so.

Revision ID: 9f4c1e2ab7d3
Revises: d5b3f8a1c920
Create Date: 2026-08-12
"""

import sqlalchemy as sa

from alembic import op

revision = "9f4c1e2ab7d3"
down_revision = "d5b3f8a1c920"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "contacts",
        sa.Column(
            "retired",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("contacts", "retired")

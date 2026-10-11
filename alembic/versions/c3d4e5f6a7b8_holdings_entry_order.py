"""holdings.created_at: clock_timestamp() so items keep their entry order

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-10-11

`now()` is fixed for a whole transaction, so every item of a purchase got
the same created_at and their order came back random. `clock_timestamp()`
advances per row, so items sort in the order they were entered. Existing
rows keep their values.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: str | Sequence[str] | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE holdings ALTER COLUMN created_at SET DEFAULT clock_timestamp()")


def downgrade() -> None:
    op.execute("ALTER TABLE holdings ALTER COLUMN created_at SET DEFAULT now()")

"""users: avatar_path (uploaded profile photo) and weight_unit preference

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-10-17

- avatar_path: object path of the user's uploaded photo in the private
  `avatars` bucket. Shown before avatar_url (the photo from Google).
- weight_unit: how weights are displayed: grams, troy ounces or tola.
  Display only; stored weights stay canonical grams.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: str | Sequence[str] | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("avatar_path", sa.String(), nullable=True))
    op.add_column(
        "users",
        sa.Column("weight_unit", sa.String(), nullable=False, server_default="g"),
    )
    op.create_check_constraint("ck_users_weight_unit", "users", "weight_unit IN ('g','oz','tola')")


def downgrade() -> None:
    op.drop_constraint("ck_users_weight_unit", "users", type_="check")
    op.drop_column("users", "weight_unit")
    op.drop_column("users", "avatar_path")

"""service_role: table privileges in public, current and future tables

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-10-18

Projects created with "Automatically expose new tables" turned off give
the Data API roles no privileges on new tables. That keeps `anon` and
`authenticated` locked out on top of RLS. `service_role` (the secret key)
still needs rows through the Data API: the e2e teardown deletes its test
user with it. Projects created with the old default already have these
grants, so this is a no-op there.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: str | Sequence[str] | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PRIVILEGES = "SELECT, INSERT, UPDATE, DELETE"


def upgrade() -> None:
    op.execute(f"GRANT {PRIVILEGES} ON ALL TABLES IN SCHEMA public TO service_role")
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT {PRIVILEGES} ON TABLES TO service_role"
    )


def downgrade() -> None:
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE {PRIVILEGES} ON TABLES FROM service_role"
    )
    op.execute(f"REVOKE {PRIVILEGES} ON ALL TABLES IN SCHEMA public FROM service_role")

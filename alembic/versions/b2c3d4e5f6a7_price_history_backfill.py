"""price_history: allow metals.dev backfill rows, one market row per day

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-10-01

- `source` gains 'metalsdev' (historical backfill). Like 'goldapi', it is a
  system-wide market source, so it must have user_id NULL.
- A partial unique index allows only one row per market source, metal,
  purity, currency and UTC day. That lets jobs re-run safely
  (ON CONFLICT DO NOTHING) and keeps history queries to one point per day.
  Manual rows are per user and may change several times a day, so they
  are excluded.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DAILY_INDEX = "uq_price_history_market_daily"


def upgrade() -> None:
    op.drop_constraint("ck_price_history_source", "price_history", type_="check")
    op.create_check_constraint(
        "ck_price_history_source",
        "price_history",
        "source IN ('goldapi','metalsdev','manual')",
    )
    op.drop_constraint("ck_price_history_source_user_match", "price_history", type_="check")
    op.create_check_constraint(
        "ck_price_history_source_user_match",
        "price_history",
        "(source IN ('goldapi','metalsdev') AND user_id IS NULL) "
        "OR (source = 'manual' AND user_id IS NOT NULL)",
    )
    op.execute(
        f"""
        CREATE UNIQUE INDEX {DAILY_INDEX} ON price_history
            (metal, purity, currency, source, ((fetched_at AT TIME ZONE 'UTC')::date))
        WHERE source <> 'manual'
        """
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {DAILY_INDEX}")
    op.execute("DELETE FROM price_history WHERE source = 'metalsdev'")
    op.drop_constraint("ck_price_history_source_user_match", "price_history", type_="check")
    op.create_check_constraint(
        "ck_price_history_source_user_match",
        "price_history",
        "(source = 'goldapi' AND user_id IS NULL) OR (source = 'manual' AND user_id IS NOT NULL)",
    )
    op.drop_constraint("ck_price_history_source", "price_history", type_="check")
    op.create_check_constraint(
        "ck_price_history_source",
        "price_history",
        "source IN ('goldapi','manual')",
    )

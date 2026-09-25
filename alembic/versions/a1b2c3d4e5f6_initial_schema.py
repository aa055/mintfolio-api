"""initial schema — users, portfolios, purchases, holdings, sales, price_history, uploaded_files

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2026-05-27

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------
# Tables managed by this migration, in FK-safe order.
# Used by upgrade() (for RLS + trigger setup) and downgrade().
# ---------------------------------------------------------------
TABLES_IN_CREATION_ORDER = [
    "users",
    "portfolios",
    "purchases",
    "holdings",
    "sales",
    "price_history",
    "uploaded_files",
]

# Tables that have an updated_at column managed by the DB trigger below.
TABLES_WITH_UPDATED_AT = [
    "users",
    "portfolios",
    "purchases",
    "holdings",
    "sales",
]


def upgrade() -> None:
    # pgcrypto provides gen_random_uuid() on older Postgres; harmless on PG 13+
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")

    # ---- DB-side updated_at trigger (defensive — ORM also sets it) ----
    op.execute(
        """
        CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # ---- users ----
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("avatar_url", sa.String(), nullable=True),
        sa.Column(
            "preferred_currency",
            sa.String(),
            nullable=False,
            server_default="AED",
        ),
        sa.Column(
            "timezone",
            sa.String(),
            nullable=False,
            server_default="Asia/Dubai",
        ),
        sa.Column(
            "default_pricing_mode",
            sa.String(),
            nullable=False,
            server_default="live",
        ),
        sa.Column("manual_gold_rate_per_gram", sa.Numeric(14, 4), nullable=True),
        sa.Column("manual_silver_rate_per_gram", sa.Numeric(14, 4), nullable=True),
        sa.Column("manual_rates_currency", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "preferred_currency IN ('AED','USD','EUR','GBP','SAR','INR')",
            name="ck_users_preferred_currency",
        ),
        sa.CheckConstraint(
            "default_pricing_mode IN ('live','manual')",
            name="ck_users_default_pricing_mode",
        ),
    )

    # ---- portfolios ----
    op.create_table(
        "portfolios",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "name", sa.String(), nullable=False, server_default="My Portfolio"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name="fk_portfolios_user_id",
        ),
        sa.UniqueConstraint("user_id", name="uq_portfolios_user_id"),
    )

    # ---- purchases ----
    op.create_table(
        "purchases",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("portfolio_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("purchase_date", sa.Date(), nullable=False),
        sa.Column("dealer", sa.String(), nullable=True),
        sa.Column("purchase_currency", sa.String(), nullable=False),
        sa.Column(
            "payment_method",
            sa.String(),
            nullable=False,
            server_default="cash",
        ),
        sa.Column("card_premium_percentage", sa.Numeric(5, 2), nullable=True),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["portfolios.id"],
            ondelete="CASCADE",
            name="fk_purchases_portfolio_id",
        ),
        sa.CheckConstraint(
            "payment_method IN ('cash','card')",
            name="ck_purchases_payment_method",
        ),
        sa.CheckConstraint(
            "card_premium_percentage IS NULL "
            "OR (card_premium_percentage >= 0 AND card_premium_percentage <= 100)",
            name="ck_purchases_card_premium_percentage_range",
        ),
        sa.CheckConstraint(
            "(payment_method = 'cash' AND card_premium_percentage IS NULL) "
            "OR (payment_method = 'card' AND card_premium_percentage IS NOT NULL)",
            name="ck_purchases_card_premium_method_match",
        ),
    )
    op.create_index(
        "ix_purchases_portfolio_id_purchase_date",
        "purchases",
        ["portfolio_id", "purchase_date"],
    )

    # ---- holdings ----
    op.create_table(
        "holdings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("purchase_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("metal", sa.String(), nullable=False),
        sa.Column("purity", sa.String(), nullable=True),
        sa.Column("form", sa.String(), nullable=True),
        sa.Column("weight_value", sa.Numeric(12, 4), nullable=False),
        sa.Column("weight_unit", sa.String(), nullable=False),
        sa.Column("weight_grams", sa.Numeric(12, 4), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("brand", sa.String(), nullable=True),
        sa.Column("purchase_price", sa.Numeric(14, 2), nullable=False),
        sa.Column("spot_rate_at_purchase", sa.Numeric(14, 4), nullable=True),
        sa.Column("premium_paid", sa.Numeric(14, 2), nullable=True),
        sa.Column("storage_location", sa.String(), nullable=True),
        sa.Column(
            "status", sa.String(), nullable=False, server_default="active"
        ),
        sa.Column("comments", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["purchase_id"],
            ["purchases.id"],
            ondelete="CASCADE",
            name="fk_holdings_purchase_id",
        ),
        sa.CheckConstraint("metal IN ('gold','silver')", name="ck_holdings_metal"),
        sa.CheckConstraint(
            "form IS NULL OR form IN ('coin','bar','bullion','jewelry','round','other')",
            name="ck_holdings_form",
        ),
        sa.CheckConstraint(
            "weight_unit IN ('g','kg','oz')",
            name="ck_holdings_weight_unit",
        ),
        sa.CheckConstraint("weight_value > 0", name="ck_holdings_weight_value_positive"),
        sa.CheckConstraint("weight_grams > 0", name="ck_holdings_weight_grams_positive"),
        sa.CheckConstraint("quantity >= 1", name="ck_holdings_quantity_min"),
        sa.CheckConstraint(
            "purchase_price >= 0", name="ck_holdings_purchase_price_nonneg"
        ),
        sa.CheckConstraint(
            "premium_paid IS NULL OR premium_paid >= 0",
            name="ck_holdings_premium_nonneg",
        ),
        sa.CheckConstraint(
            "status IN ('active','sold')", name="ck_holdings_status"
        ),
    )
    op.create_index("ix_holdings_purchase_id", "holdings", ["purchase_id"])
    op.create_index("ix_holdings_metal_status", "holdings", ["metal", "status"])

    # ---- sales ----
    op.create_table(
        "sales",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("holding_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sale_price", sa.Numeric(14, 2), nullable=False),
        sa.Column("sale_currency", sa.String(), nullable=False),
        sa.Column("sale_date", sa.Date(), nullable=False),
        sa.Column("sold_to", sa.String(), nullable=True),
        sa.Column("spot_rate_at_sale", sa.Numeric(14, 4), nullable=True),
        sa.Column(
            "fees", sa.Numeric(14, 2), nullable=False, server_default="0"
        ),
        sa.Column("comments", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["holding_id"],
            ["holdings.id"],
            ondelete="CASCADE",
            name="fk_sales_holding_id",
        ),
        sa.UniqueConstraint("holding_id", name="uq_sales_holding_id"),
        sa.CheckConstraint("sale_price >= 0", name="ck_sales_sale_price_nonneg"),
        sa.CheckConstraint("fees >= 0", name="ck_sales_fees_nonneg"),
    )

    # ---- price_history ----
    op.create_table(
        "price_history",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("metal", sa.String(), nullable=False),
        sa.Column("purity", sa.String(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("rate_per_gram", sa.Numeric(14, 4), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name="fk_price_history_user_id",
        ),
        sa.CheckConstraint("metal IN ('gold','silver')", name="ck_price_history_metal"),
        sa.CheckConstraint(
            "source IN ('goldapi','manual')", name="ck_price_history_source"
        ),
        sa.CheckConstraint("rate_per_gram >= 0", name="ck_price_history_rate_nonneg"),
        sa.CheckConstraint(
            "(source = 'goldapi' AND user_id IS NULL) "
            "OR (source = 'manual' AND user_id IS NOT NULL)",
            name="ck_price_history_source_user_match",
        ),
    )
    op.create_index(
        "ix_price_history_lookup",
        "price_history",
        ["metal", "purity", "source", "fetched_at"],
    )
    op.create_index(
        "ix_price_history_manual_user_lookup",
        "price_history",
        ["user_id", "metal", "purity", "fetched_at"],
        postgresql_where=sa.text("source = 'manual'"),
    )

    # ---- uploaded_files ----
    op.create_table(
        "uploaded_files",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("purchase_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("storage_path", sa.String(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("mime_type", sa.String(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["purchase_id"],
            ["purchases.id"],
            ondelete="CASCADE",
            name="fk_uploaded_files_purchase_id",
        ),
        sa.UniqueConstraint(
            "storage_path", name="uq_uploaded_files_storage_path"
        ),
        sa.CheckConstraint(
            "mime_type IN ('image/jpeg','image/png','application/pdf')",
            name="ck_uploaded_files_mime_type",
        ),
        sa.CheckConstraint(
            "size_bytes > 0 AND size_bytes <= 5242880",
            name="ck_uploaded_files_size",
        ),
    )
    op.create_index(
        "ix_uploaded_files_purchase_id", "uploaded_files", ["purchase_id"]
    )

    # ---- DB-side updated_at triggers ----
    for table in TABLES_WITH_UPDATED_AT:
        op.execute(
            f"""
            CREATE TRIGGER set_updated_at_{table}
            BEFORE UPDATE ON {table}
            FOR EACH ROW
            EXECUTE FUNCTION set_updated_at();
            """
        )

    # ---- Enable RLS on every table (defense-in-depth — no policies) ----
    for table in TABLES_IN_CREATION_ORDER:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")


def downgrade() -> None:
    # Drop triggers first (so dropping tables doesn't error on dependent triggers)
    for table in TABLES_WITH_UPDATED_AT:
        op.execute(f"DROP TRIGGER IF EXISTS set_updated_at_{table} ON {table};")

    # Drop tables in reverse order
    for table in reversed(TABLES_IN_CREATION_ORDER):
        op.drop_table(table)

    op.execute("DROP FUNCTION IF EXISTS set_updated_at();")

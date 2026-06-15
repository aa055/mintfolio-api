from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class PriceHistory(Base):
    """Append-only price snapshots.

    Two sources coexist:
      - 'goldapi': system-wide rows written by the daily cron. user_id IS NULL.
      - 'manual':  per-user rows when the user enters their own rate. user_id NOT NULL.

    Rows are immutable — no `updated_at`. The latest row per (metal, purity,
    source[, user_id]) wins for valuation lookups.
    """

    __tablename__ = "price_history"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=func.gen_random_uuid(),
    )
    metal: Mapped[str] = mapped_column(String, nullable=False)
    purity: Mapped[str] = mapped_column(String, nullable=False)
    currency: Mapped[str] = mapped_column(String, nullable=False)
    rate_per_gram: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped[User | None] = relationship(
        "User",
        back_populates="manual_prices",
        lazy="raise",
    )

    __table_args__ = (
        CheckConstraint("metal IN ('gold','silver')", name="ck_price_history_metal"),
        CheckConstraint(
            "source IN ('goldapi','manual')",
            name="ck_price_history_source",
        ),
        CheckConstraint("rate_per_gram >= 0", name="ck_price_history_rate_nonneg"),
        # Source/user_id consistency: goldapi rows have no user, manual rows must have one
        CheckConstraint(
            "(source = 'goldapi' AND user_id IS NULL) "
            "OR (source = 'manual' AND user_id IS NOT NULL)",
            name="ck_price_history_source_user_match",
        ),
        Index(
            "ix_price_history_lookup",
            "metal",
            "purity",
            "source",
            "fetched_at",
        ),
        Index(
            "ix_price_history_manual_user_lookup",
            "user_id",
            "metal",
            "purity",
            "fetched_at",
            postgresql_where="source = 'manual'",
        ),
    )

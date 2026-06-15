from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.holding import Holding


class Sale(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A sale of a holding. UNIQUE on holding_id enforces 'no partial sales' for MVP."""

    __tablename__ = "sales"

    holding_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("holdings.id", ondelete="CASCADE"),
        nullable=False,
    )
    sale_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    sale_currency: Mapped[str] = mapped_column(String, nullable=False)
    sale_date: Mapped[date] = mapped_column(Date, nullable=False)
    sold_to: Mapped[str | None] = mapped_column(String, nullable=True)
    spot_rate_at_sale: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 4), nullable=True
    )
    fees: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, server_default="0"
    )
    comments: Mapped[str | None] = mapped_column(String, nullable=True)

    holding: Mapped[Holding] = relationship(
        "Holding",
        back_populates="sale",
        lazy="raise",
    )

    __table_args__ = (
        UniqueConstraint("holding_id", name="uq_sales_holding_id"),
        CheckConstraint("sale_price >= 0", name="ck_sales_sale_price_nonneg"),
        CheckConstraint("fees >= 0", name="ck_sales_fees_nonneg"),
    )

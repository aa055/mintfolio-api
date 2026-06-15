from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.purchase import Purchase
    from app.models.sale import Sale


class Holding(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A line item — one type of physical metal bought in a purchase.

    `weight_value` is what the user typed, `weight_unit` is what they picked,
    `weight_grams` is the canonical value used for all math (computed on write).
    """

    __tablename__ = "holdings"

    purchase_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("purchases.id", ondelete="CASCADE"),
        nullable=False,
    )

    metal: Mapped[str] = mapped_column(String, nullable=False)
    purity: Mapped[str | None] = mapped_column(String, nullable=True)
    form: Mapped[str | None] = mapped_column(String, nullable=True)

    weight_value: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    weight_unit: Mapped[str] = mapped_column(String, nullable=False)
    weight_grams: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    quantity: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )

    brand: Mapped[str | None] = mapped_column(String, nullable=True)

    purchase_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    spot_rate_at_purchase: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 4), nullable=True
    )
    premium_paid: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)

    storage_location: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(
        String, nullable=False, server_default="active"
    )
    comments: Mapped[str | None] = mapped_column(String, nullable=True)

    purchase: Mapped[Purchase] = relationship(
        "Purchase",
        back_populates="holdings",
        lazy="raise",
    )
    sale: Mapped[Sale | None] = relationship(
        "Sale",
        back_populates="holding",
        cascade="all, delete-orphan",
        uselist=False,
        lazy="raise",
    )

    __table_args__ = (
        CheckConstraint("metal IN ('gold','silver')", name="ck_holdings_metal"),
        CheckConstraint(
            "form IS NULL OR form IN ('coin','bar','bullion','jewelry','round','other')",
            name="ck_holdings_form",
        ),
        CheckConstraint(
            "weight_unit IN ('g','kg','oz')",
            name="ck_holdings_weight_unit",
        ),
        CheckConstraint("weight_value > 0", name="ck_holdings_weight_value_positive"),
        CheckConstraint("weight_grams > 0", name="ck_holdings_weight_grams_positive"),
        CheckConstraint("quantity >= 1", name="ck_holdings_quantity_min"),
        CheckConstraint("purchase_price >= 0", name="ck_holdings_purchase_price_nonneg"),
        CheckConstraint(
            "premium_paid IS NULL OR premium_paid >= 0",
            name="ck_holdings_premium_nonneg",
        ),
        CheckConstraint(
            "status IN ('active','sold')",
            name="ck_holdings_status",
        ),
        Index("ix_holdings_purchase_id", "purchase_id"),
        Index("ix_holdings_metal_status", "metal", "status"),
    )

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.holding import Holding
    from app.models.portfolio import Portfolio
    from app.models.uploaded_file import UploadedFile


class Purchase(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A single dealer order.

    Owns the metadata shared across all items bought together: dealer, date,
    currency, payment method, receipt files.
    """

    __tablename__ = "purchases"

    portfolio_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("portfolios.id", ondelete="CASCADE"),
        nullable=False,
    )
    purchase_date: Mapped[date] = mapped_column(Date, nullable=False)
    dealer: Mapped[str | None] = mapped_column(String, nullable=True)
    purchase_currency: Mapped[str] = mapped_column(String, nullable=False)
    payment_method: Mapped[str] = mapped_column(
        String, nullable=False, server_default="cash"
    )
    card_premium_percentage: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(String, nullable=True)

    portfolio: Mapped[Portfolio] = relationship(
        "Portfolio",
        back_populates="purchases",
        lazy="raise",
    )
    holdings: Mapped[list[Holding]] = relationship(
        "Holding",
        back_populates="purchase",
        cascade="all, delete-orphan",
        lazy="raise",
    )
    files: Mapped[list[UploadedFile]] = relationship(
        "UploadedFile",
        back_populates="purchase",
        cascade="all, delete-orphan",
        lazy="raise",
    )

    __table_args__ = (
        CheckConstraint(
            "payment_method IN ('cash','card')",
            name="ck_purchases_payment_method",
        ),
        CheckConstraint(
            "card_premium_percentage IS NULL "
            "OR (card_premium_percentage >= 0 AND card_premium_percentage <= 100)",
            name="ck_purchases_card_premium_percentage_range",
        ),
        # Cross-column rule: percentage is NULL for cash, NOT NULL for card
        CheckConstraint(
            "(payment_method = 'cash' AND card_premium_percentage IS NULL) "
            "OR (payment_method = 'card' AND card_premium_percentage IS NOT NULL)",
            name="ck_purchases_card_premium_method_match",
        ),
        Index(
            "ix_purchases_portfolio_id_purchase_date",
            "portfolio_id",
            "purchase_date",
        ),
    )

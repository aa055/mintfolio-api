from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.purchase import Purchase
    from app.models.user import User


class Portfolio(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A portfolio container. One per user in MVP — UNIQUE on user_id enforces this."""

    __tablename__ = "portfolios"

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(
        String, nullable=False, server_default="My Portfolio"
    )

    user: Mapped[User] = relationship(
        "User",
        back_populates="portfolio",
        lazy="raise",
    )
    purchases: Mapped[list[Purchase]] = relationship(
        "Purchase",
        back_populates="portfolio",
        cascade="all, delete-orphan",
        lazy="raise",
    )

    __table_args__ = (
        UniqueConstraint("user_id", name="uq_portfolios_user_id"),
    )

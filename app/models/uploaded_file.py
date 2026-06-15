from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.purchase import Purchase


class UploadedFile(Base):
    """A receipt or document attached to a purchase.

    Bytes live in the Supabase Storage `receipts` bucket; this row holds
    the path and display metadata.
    """

    __tablename__ = "uploaded_files"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=func.gen_random_uuid(),
    )
    purchase_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("purchases.id", ondelete="CASCADE"),
        nullable=False,
    )
    storage_path: Mapped[str] = mapped_column(String, nullable=False)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    mime_type: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    purchase: Mapped[Purchase] = relationship(
        "Purchase",
        back_populates="files",
        lazy="raise",
    )

    __table_args__ = (
        UniqueConstraint("storage_path", name="uq_uploaded_files_storage_path"),
        CheckConstraint(
            "mime_type IN ('image/jpeg','image/png','application/pdf')",
            name="ck_uploaded_files_mime_type",
        ),
        CheckConstraint(
            "size_bytes > 0 AND size_bytes <= 5242880",
            name="ck_uploaded_files_size",
        ),
        Index("ix_uploaded_files_purchase_id", "purchase_id"),
    )

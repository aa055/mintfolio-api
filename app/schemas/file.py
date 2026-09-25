from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

AllowedMime = Literal["image/jpeg", "image/png", "application/pdf"]


class SignUploadRequest(BaseModel):
    """Asks the server for a signed upload URL for one file."""

    filename: Annotated[str, Field(min_length=1, max_length=200)]
    mime_type: AllowedMime
    size_bytes: Annotated[int, Field(gt=0, le=5 * 1024 * 1024)]  # <= 5 MB


class SignUploadResponse(BaseModel):
    """Hands the client what it needs to upload directly to Storage."""

    upload_url: str
    storage_path: str


class RegisterFileRequest(BaseModel):
    """Confirms a successful upload — server records the row."""

    storage_path: Annotated[str, Field(min_length=1, max_length=500)]
    filename: Annotated[str, Field(min_length=1, max_length=200)]
    mime_type: AllowedMime
    size_bytes: Annotated[int, Field(gt=0, le=5 * 1024 * 1024)]


class FileOut(BaseModel):
    """Returned in purchase listings — `download_url` is short-lived signed."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    filename: str
    mime_type: str
    size_bytes: int
    storage_path: str
    uploaded_at: datetime
    download_url: str | None = None

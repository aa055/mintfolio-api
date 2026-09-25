"""Thin async client for the Supabase Storage REST API.

Uses the project's `service_role` key — the same key Supabase admin tools
use — so it bypasses RLS and can manage any bucket/object. NEVER expose
the service role key to the browser.
"""

from __future__ import annotations

import mimetypes
import uuid
from pathlib import PurePosixPath
from typing import Final

import httpx

from app.config import get_settings

ALLOWED_MIME_TYPES: Final = ("image/jpeg", "image/png", "application/pdf")
MAX_FILE_SIZE_BYTES: Final = 5 * 1024 * 1024  # 5 MB — matches uploaded_files CHECK

_MIME_TO_EXT: Final = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "application/pdf": "pdf",
}


class StorageError(Exception):
    """Raised when a Supabase Storage call fails."""


def _settings():
    return get_settings()


def _service_headers() -> dict[str, str]:
    s = _settings()
    return {
        "Authorization": f"Bearer {s.supabase_service_role_key}",
        "apikey": s.supabase_service_role_key,
    }


def _storage_base() -> str:
    return f"{_settings().supabase_url}/storage/v1"


def build_storage_path(
    *,
    user_id: str,
    purchase_id: str,
    original_filename: str | None,
    mime_type: str,
) -> str:
    """Compose a collision-safe path inside the receipts bucket.

    Pattern: `user-{uid}/purchase-{pid}/{uuid}.{ext}`. The user's filename
    is intentionally NOT used as a path segment — uuid + mime-derived
    extension keeps things safe regardless of what the browser sends.
    """
    if mime_type not in ALLOWED_MIME_TYPES:
        raise StorageError(f"Disallowed MIME type: {mime_type!r}")

    # Prefer the extension from the filename, but only if it matches the MIME.
    ext = _MIME_TO_EXT[mime_type]
    if original_filename:
        suffix = PurePosixPath(original_filename).suffix.lstrip(".").lower()
        if suffix in {"jpg", "jpeg", "png", "pdf"}:
            # normalize jpeg -> jpg
            ext = "jpg" if suffix == "jpeg" else suffix

    return f"user-{user_id}/purchase-{purchase_id}/{uuid.uuid4().hex}.{ext}"


async def ensure_bucket() -> None:
    """Create the receipts bucket if it doesn't already exist.

    Idempotent — safe to call on every startup. Sets MIME whitelist and
    size cap at the bucket level so even a misconfigured client can't
    sneak past our validation.
    """
    s = _settings()
    bucket = s.supabase_storage_bucket
    async with httpx.AsyncClient(timeout=15.0) as client:
        # GET — exists check
        r = await client.get(
            f"{_storage_base()}/bucket/{bucket}",
            headers=_service_headers(),
        )
        if r.status_code == 200:
            return
        if r.status_code not in (400, 404):
            raise StorageError(
                f"Unexpected status {r.status_code} checking bucket: {r.text}"
            )

        # Create
        r = await client.post(
            f"{_storage_base()}/bucket",
            headers={**_service_headers(), "Content-Type": "application/json"},
            json={
                "id": bucket,
                "name": bucket,
                "public": False,
                "file_size_limit": MAX_FILE_SIZE_BYTES,
                "allowed_mime_types": list(ALLOWED_MIME_TYPES),
            },
        )
        if r.status_code not in (200, 201, 409):
            raise StorageError(
                f"Failed to create bucket {bucket!r}: {r.status_code} {r.text}"
            )


async def create_signed_upload_url(
    storage_path: str,
    *,
    expires_in_seconds: int = 600,
) -> str:
    """Return a one-time signed URL for a PUT upload.

    The returned URL is fully-qualified — the client just PUTs the file
    bytes to it with `Content-Type: <mime>` and no Authorization header.
    """
    s = _settings()
    bucket = s.supabase_storage_bucket
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(
            f"{_storage_base()}/object/upload/sign/{bucket}/{storage_path}",
            headers={**_service_headers(), "Content-Type": "application/json"},
            json={"expiresIn": expires_in_seconds},
        )
    if r.status_code not in (200, 201):
        raise StorageError(
            f"Sign upload failed for {storage_path!r}: {r.status_code} {r.text}"
        )
    body = r.json()
    relative = body.get("url")
    if not relative:
        raise StorageError(f"Unexpected sign-upload response: {body}")
    # The response gives us /object/upload/sign/{bucket}/{path}?token=...
    # We prepend the storage base to make it absolute.
    if relative.startswith("/storage/v1"):
        return f"{s.supabase_url}{relative}"
    return f"{_storage_base()}{relative}"


async def create_signed_download_url(
    storage_path: str,
    *,
    expires_in_seconds: int = 300,
) -> str:
    """Return a short-lived signed GET URL for reading the object."""
    s = _settings()
    bucket = s.supabase_storage_bucket
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(
            f"{_storage_base()}/object/sign/{bucket}/{storage_path}",
            headers={**_service_headers(), "Content-Type": "application/json"},
            json={"expiresIn": expires_in_seconds},
        )
    if r.status_code not in (200, 201):
        raise StorageError(
            f"Sign download failed for {storage_path!r}: {r.status_code} {r.text}"
        )
    body = r.json()
    relative = body.get("signedURL") or body.get("signedUrl")
    if not relative:
        raise StorageError(f"Unexpected sign-download response: {body}")
    if relative.startswith("/storage/v1"):
        return f"{s.supabase_url}{relative}"
    return f"{_storage_base()}{relative}"


async def delete_object(storage_path: str) -> None:
    """Remove the object from the bucket. 404 is treated as success."""
    s = _settings()
    bucket = s.supabase_storage_bucket
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.delete(
            f"{_storage_base()}/object/{bucket}/{storage_path}",
            headers=_service_headers(),
        )
    if r.status_code in (200, 204, 404):
        return
    raise StorageError(
        f"Delete failed for {storage_path!r}: {r.status_code} {r.text}"
    )


def guess_mime_type(filename: str) -> str | None:
    """Conservative MIME guess for clients that don't send Content-Type."""
    mt, _ = mimetypes.guess_type(filename)
    return mt

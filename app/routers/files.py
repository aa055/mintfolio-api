import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import CurrentUserDep
from app.models.uploaded_file import UploadedFile
from app.schemas.file import (
    FileOut,
    RegisterFileRequest,
    SignUploadRequest,
    SignUploadResponse,
)
from app.services.portfolio_access import OwnedFileDep, OwnedPurchaseDep
from app.services.storage import (
    StorageError,
    build_storage_path,
    create_signed_download_url,
    create_signed_upload_url,
    delete_object,
)

router = APIRouter(tags=["files"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

# The final path segment `build_storage_path` generates: `<uuid hex>.<ext>`.
_OBJECT_NAME_RE = re.compile(r"[0-9a-f]{32}\.(jpg|png|pdf)")


@router.post(
    "/purchases/{purchase_id}/files/sign-upload",
    response_model=SignUploadResponse,
)
async def sign_upload(
    body: SignUploadRequest,
    purchase: OwnedPurchaseDep,
    current: CurrentUserDep,
) -> SignUploadResponse:
    """Return a one-shot signed URL the client can PUT the file bytes to.

    Path is derived server-side from the user + purchase + a UUID; the
    client never picks the storage path, so naming is consistently scoped
    and safe.
    """
    storage_path = build_storage_path(
        user_id=current.id,
        purchase_id=str(purchase.id),
        original_filename=body.filename,
        mime_type=body.mime_type,
    )
    try:
        upload_url = await create_signed_upload_url(storage_path)
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Storage error: {exc}",
        ) from exc
    return SignUploadResponse(upload_url=upload_url, storage_path=storage_path)


@router.post(
    "/purchases/{purchase_id}/files",
    response_model=FileOut,
    status_code=status.HTTP_201_CREATED,
)
async def register_file(
    body: RegisterFileRequest,
    purchase: OwnedPurchaseDep,
    current: CurrentUserDep,
    session: SessionDep,
) -> FileOut:
    """Record an uploaded file after the client confirms a successful PUT.

    Pre-check that the storage path actually lives under this purchase's
    expected prefix, so a malicious caller can't register a row that
    points at someone else's object.
    """
    expected_prefix = f"user-{current.id}/purchase-{purchase.id}/"
    object_name = body.storage_path.removeprefix(expected_prefix)
    if object_name == body.storage_path or not _OBJECT_NAME_RE.fullmatch(object_name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="storage_path is not under this purchase's prefix",
        )

    file = UploadedFile(
        purchase_id=purchase.id,
        storage_path=body.storage_path,
        filename=body.filename,
        mime_type=body.mime_type,
        size_bytes=body.size_bytes,
    )
    session.add(file)
    await session.commit()
    await session.refresh(file)

    out = FileOut.model_validate(file)
    try:
        out.download_url = await create_signed_download_url(file.storage_path)
    except StorageError:
        out.download_url = None
    return out


@router.delete(
    "/files/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_file(
    file: OwnedFileDep,
    session: SessionDep,
) -> None:
    """Remove the storage object and the DB row.

    Storage delete first — if it fails we surface the error and keep the
    DB row, so the user can retry. The reverse order would orphan bytes.
    """
    try:
        await delete_object(file.storage_path)
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Storage error: {exc}",
        ) from exc

    await session.delete(file)
    await session.commit()

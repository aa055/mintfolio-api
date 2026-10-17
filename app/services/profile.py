"""Profile responses shared by the auth and prices routers."""

from app.models.user import User
from app.schemas.user import UserOut
from app.services.storage import StorageError, avatar_bucket, create_signed_download_url

# Photo links are re-signed on every profile read; an hour outlasts a page.
PHOTO_URL_TTL = 3600


async def user_out(user: User) -> UserOut:
    """UserOut with a fresh signed URL for the uploaded photo, if any."""
    out = UserOut.model_validate(user)
    if user.avatar_path:
        try:
            out.photo_url = await create_signed_download_url(
                user.avatar_path, bucket=avatar_bucket(), expires_in_seconds=PHOTO_URL_TTL
            )
        except StorageError:
            out.photo_url = None  # fall back to avatar_url / initials
    return out

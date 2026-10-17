import contextlib
import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import CurrentUserDep
from app.models.portfolio import Portfolio
from app.models.user import User
from app.schemas.user import (
    AuthSyncRequest,
    AvatarSetRequest,
    AvatarSignRequest,
    AvatarSignResponse,
    MeResponse,
    PortfolioOut,
    UserOut,
    UserSettingsUpdate,
)
from app.services.profile import user_out
from app.services.storage import (
    StorageError,
    avatar_bucket,
    build_avatar_path,
    create_signed_upload_url,
    delete_object,
)

router = APIRouter(tags=["auth"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def _get_user(session: AsyncSession, user_id: str) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not synced. Call POST /auth/sync first.",
        )
    return user


async def _ensure_portfolio(session: AsyncSession, user: User) -> Portfolio:
    """Return the user's portfolio, creating it on first call."""
    stmt = select(Portfolio).where(Portfolio.user_id == user.id)
    portfolio = (await session.execute(stmt)).scalar_one_or_none()
    if portfolio is None:
        portfolio = Portfolio(user_id=user.id)
        session.add(portfolio)
        await session.flush()
    return portfolio


@router.post("/sync", response_model=MeResponse, status_code=status.HTTP_200_OK)
async def sync_user(
    body: AuthSyncRequest,
    current: CurrentUserDep,
    session: SessionDep,
) -> MeResponse:
    """Idempotent: ensure a `users` row + `portfolios` row exist for the
    authenticated Supabase user. Called by the frontend after signup and
    on every login.

    The name and photo from signup / Google only fill empty fields, so a
    name the user changed on their profile isn't reset at the next login.
    The email always follows the auth provider.
    """
    if not current.email:
        # Should never happen for a verified Supabase token, but guard anyway.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="JWT is missing the email claim — cannot sync user.",
        )

    user = await session.get(User, current.id)
    if user is None:
        user = User(
            id=current.id,
            email=current.email,
            display_name=body.display_name,
            avatar_url=body.avatar_url,
        )
        session.add(user)
        await session.flush()
    else:
        if user.email != current.email:
            user.email = current.email
        if body.display_name and not user.display_name:
            user.display_name = body.display_name
        if body.avatar_url and not user.avatar_url:
            user.avatar_url = body.avatar_url

    portfolio = await _ensure_portfolio(session, user)
    await session.commit()

    await session.refresh(user)
    await session.refresh(portfolio)
    return MeResponse(user=await user_out(user), portfolio=PortfolioOut.model_validate(portfolio))


@router.get("/me", response_model=MeResponse)
async def get_me(
    current: CurrentUserDep,
    session: SessionDep,
) -> MeResponse:
    """Returns the current user's profile and portfolio.

    Returns 404 if the user hasn't been synced yet — clients should call
    `POST /auth/sync` immediately after a successful Supabase login.
    """
    user = await session.get(User, current.id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not synced. Call POST /auth/sync first.",
        )

    stmt = select(Portfolio).where(Portfolio.user_id == user.id)
    portfolio = (await session.execute(stmt)).scalar_one_or_none()
    if portfolio is None:
        # Self-heal: portfolio should always exist alongside a synced user.
        portfolio = Portfolio(user_id=user.id)
        session.add(portfolio)
        await session.commit()
        await session.refresh(portfolio)

    return MeResponse(user=await user_out(user), portfolio=PortfolioOut.model_validate(portfolio))


@router.patch("/me", response_model=UserOut)
async def update_me(
    body: UserSettingsUpdate,
    current: CurrentUserDep,
    session: SessionDep,
) -> UserOut:
    """Update profile settings. Only fields present in the body change."""
    user = await _get_user(session, current.id)
    for field in body.model_fields_set:
        setattr(user, field, getattr(body, field))
    await session.commit()
    await session.refresh(user)
    return await user_out(user)


@router.post("/me/avatar/sign-upload", response_model=AvatarSignResponse)
async def sign_avatar_upload(
    body: AvatarSignRequest, current: CurrentUserDep
) -> AvatarSignResponse:
    """One-shot signed URL to PUT a new profile photo to (browser → Storage)."""
    path = build_avatar_path(current.id, body.mime_type)
    try:
        url = await create_signed_upload_url(path, bucket=avatar_bucket())
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Storage error: {exc}"
        ) from exc
    return AvatarSignResponse(upload_url=url, storage_path=path)


@router.put("/me/avatar", response_model=UserOut)
async def set_avatar(
    body: AvatarSetRequest, current: CurrentUserDep, session: SessionDep
) -> UserOut:
    """Use an uploaded photo as the profile picture; the previous one is deleted."""
    if not re.fullmatch(
        rf"user-{re.escape(current.id)}/[0-9a-f]{{32}}\.(jpg|png|webp)", body.storage_path
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="storage_path is not one of this user's avatar uploads",
        )
    user = await _get_user(session, current.id)
    previous = user.avatar_path
    user.avatar_path = body.storage_path
    await session.commit()
    await session.refresh(user)
    if previous and previous != body.storage_path:
        # An orphaned old photo is harmless; don't fail the change over it.
        with contextlib.suppress(StorageError):
            await delete_object(previous, bucket=avatar_bucket())
    return await user_out(user)


@router.delete("/me/avatar", response_model=UserOut)
async def remove_avatar(current: CurrentUserDep, session: SessionDep) -> UserOut:
    """Remove the uploaded photo (the Google photo / initials show again)."""
    user = await _get_user(session, current.id)
    if user.avatar_path:
        try:
            await delete_object(user.avatar_path, bucket=avatar_bucket())
        except StorageError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Storage error: {exc}"
            ) from exc
        user.avatar_path = None
        await session.commit()
        await session.refresh(user)
    return await user_out(user)

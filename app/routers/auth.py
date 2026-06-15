from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import CurrentUserDep
from app.models.portfolio import Portfolio
from app.models.user import User
from app.schemas.user import AuthSyncRequest, MeResponse, PortfolioOut, UserOut

router = APIRouter(tags=["auth"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


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
    authenticated Supabase user. Called by the frontend right after signup
    or login. Safe to call on every login — it just refreshes email /
    display_name / avatar_url if the JWT carries newer values.
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
        # Refresh fields that may have changed in the IdP since last sync.
        if user.email != current.email:
            user.email = current.email
        if body.display_name and user.display_name != body.display_name:
            user.display_name = body.display_name
        if body.avatar_url and user.avatar_url != body.avatar_url:
            user.avatar_url = body.avatar_url

    portfolio = await _ensure_portfolio(session, user)
    await session.commit()

    await session.refresh(user)
    await session.refresh(portfolio)
    return MeResponse(
        user=UserOut.model_validate(user),
        portfolio=PortfolioOut.model_validate(portfolio),
    )


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

    return MeResponse(
        user=UserOut.model_validate(user),
        portfolio=PortfolioOut.model_validate(portfolio),
    )

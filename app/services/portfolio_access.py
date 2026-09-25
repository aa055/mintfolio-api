"""Ownership-scoped portfolio access dependencies.

Any endpoint that reads or writes data inside a specific portfolio should
depend on these so the URL's `portfolio_id` is gated by ownership rather
than trusted blindly.
"""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import CurrentUserDep
from app.models.portfolio import Portfolio
from app.models.purchase import Purchase
from app.models.uploaded_file import UploadedFile


async def get_owned_portfolio(
    portfolio_id: UUID,
    current: CurrentUserDep,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Portfolio:
    """Return the portfolio if the current user owns it, else 404.

    We intentionally return 404 (not 403) so we don't leak the existence
    of portfolios owned by other users.
    """
    stmt = select(Portfolio).where(
        Portfolio.id == portfolio_id,
        Portfolio.user_id == current.id,
    )
    portfolio = (await session.execute(stmt)).scalar_one_or_none()
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Portfolio not found",
        )
    return portfolio


OwnedPortfolioDep = Annotated[Portfolio, Depends(get_owned_portfolio)]


async def get_owned_purchase(
    purchase_id: UUID,
    current: CurrentUserDep,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Purchase:
    """Return the purchase if the current user owns the parent portfolio."""
    stmt = (
        select(Purchase)
        .join(Portfolio, Purchase.portfolio_id == Portfolio.id)
        .where(Purchase.id == purchase_id, Portfolio.user_id == current.id)
    )
    purchase = (await session.execute(stmt)).scalar_one_or_none()
    if purchase is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Purchase not found",
        )
    return purchase


OwnedPurchaseDep = Annotated[Purchase, Depends(get_owned_purchase)]


async def get_owned_file(
    file_id: UUID,
    current: CurrentUserDep,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UploadedFile:
    """Return the file if the current user owns it transitively (file→purchase→portfolio→user)."""
    stmt = (
        select(UploadedFile)
        .join(Purchase, UploadedFile.purchase_id == Purchase.id)
        .join(Portfolio, Purchase.portfolio_id == Portfolio.id)
        .where(UploadedFile.id == file_id, Portfolio.user_id == current.id)
    )
    file = (await session.execute(stmt)).scalar_one_or_none()
    if file is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found",
        )
    return file


OwnedFileDep = Annotated[UploadedFile, Depends(get_owned_file)]

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_session
from app.models.holding import Holding
from app.models.purchase import Purchase
from app.schemas.file import FileOut
from app.schemas.purchase import (
    HoldingOut,
    PurchaseCreate,
    PurchaseListResponse,
    PurchaseOut,
)
from app.services.portfolio_access import OwnedPortfolioDep
from app.services.storage import StorageError, create_signed_download_url
from app.services.weight import to_grams

router = APIRouter(tags=["purchases"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def _purchase_to_out(
    purchase: Purchase, *, include_download_urls: bool = True
) -> PurchaseOut:
    """Build the response object — total, items, and (optionally) signed
    download URLs for each attached file. Set `include_download_urls=False`
    when responding to a write that just created the purchase with no files."""
    items = [HoldingOut.model_validate(h) for h in purchase.holdings]
    total = sum((h.purchase_price for h in purchase.holdings), Decimal("0"))

    files: list[FileOut] = []
    for f in purchase.files:
        out = FileOut.model_validate(f)
        if include_download_urls:
            try:
                out.download_url = await create_signed_download_url(f.storage_path)
            except StorageError:
                out.download_url = None
        files.append(out)

    return PurchaseOut(
        id=purchase.id,
        portfolio_id=purchase.portfolio_id,
        purchase_date=purchase.purchase_date,
        dealer=purchase.dealer,
        purchase_currency=purchase.purchase_currency,
        payment_method=purchase.payment_method,  # type: ignore[arg-type]
        card_premium_percentage=purchase.card_premium_percentage,
        notes=purchase.notes,
        created_at=purchase.created_at,
        updated_at=purchase.updated_at,
        items=items,
        total_amount=total,
        files=files,
    )


@router.post(
    "/portfolios/{portfolio_id}/purchases",
    response_model=PurchaseOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_purchase(
    body: PurchaseCreate,
    portfolio: OwnedPortfolioDep,
    session: SessionDep,
) -> PurchaseOut:
    """Create a purchase + its line items atomically.

    The whole operation runs in one transaction — if any holding fails
    validation (DB CHECK constraint, etc.) the whole purchase is rolled back.
    """
    purchase = Purchase(
        portfolio_id=portfolio.id,
        purchase_date=body.purchase_date,
        dealer=body.dealer,
        purchase_currency=body.purchase_currency,
        payment_method=body.payment_method,
        card_premium_percentage=body.card_premium_percentage,
        notes=body.notes,
    )
    session.add(purchase)
    await session.flush()  # populate purchase.id

    for item in body.items:
        holding = Holding(
            purchase_id=purchase.id,
            metal=item.metal,
            purity=item.purity,
            form=item.form,
            weight_value=item.weight_value,
            weight_unit=item.weight_unit,
            weight_grams=to_grams(item.weight_value, item.weight_unit),
            quantity=item.quantity,
            brand=item.brand,
            purchase_price=item.purchase_price,
            spot_rate_at_purchase=item.spot_rate_at_purchase,
            premium_paid=item.premium_paid,
            storage_location=item.storage_location,
            comments=item.comments,
        )
        session.add(holding)

    await session.commit()

    # Re-read with holdings + files eagerly loaded for the response.
    stmt = (
        select(Purchase)
        .where(Purchase.id == purchase.id)
        .options(selectinload(Purchase.holdings), selectinload(Purchase.files))
    )
    fresh = (await session.execute(stmt)).scalar_one()
    return await _purchase_to_out(fresh, include_download_urls=False)


@router.get(
    "/portfolios/{portfolio_id}/purchases",
    response_model=PurchaseListResponse,
)
async def list_purchases(
    portfolio: OwnedPortfolioDep,
    session: SessionDep,
) -> PurchaseListResponse:
    """List all purchases in the portfolio, newest first, with their line items + files."""
    stmt = (
        select(Purchase)
        .where(Purchase.portfolio_id == portfolio.id)
        .options(
            selectinload(Purchase.holdings),
            selectinload(Purchase.files),
        )
        .order_by(
            Purchase.purchase_date.desc(),
            Purchase.created_at.desc(),
        )
    )
    purchases = (await session.execute(stmt)).scalars().all()
    out = [await _purchase_to_out(p) for p in purchases]
    return PurchaseListResponse(purchases=out)

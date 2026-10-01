import asyncio
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_session
from app.models.holding import Holding
from app.models.purchase import Purchase
from app.models.uploaded_file import UploadedFile
from app.schemas.file import FileOut
from app.schemas.purchase import (
    HoldingCreate,
    HoldingOut,
    PurchaseCreate,
    PurchaseListResponse,
    PurchaseOut,
    PurchaseUpdate,
)
from app.services.portfolio_access import OwnedPortfolioDep, OwnedPurchaseDep
from app.services.storage import StorageError, create_signed_download_url, delete_objects
from app.services.weight import to_grams

router = APIRouter(tags=["purchases"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

# Everything a purchase response needs, loaded up front (relationships are lazy="raise").
_FULL_PURCHASE = (
    selectinload(Purchase.holdings).selectinload(Holding.sale),
    selectinload(Purchase.files),
)

# Purchase-level fields shared by create and update bodies.
_PURCHASE_FIELDS = (
    "purchase_date",
    "dealer",
    "purchase_currency",
    "payment_method",
    "card_premium_percentage",
    "notes",
)


async def _signed_url_or_none(storage_path: str) -> str | None:
    try:
        return await create_signed_download_url(storage_path)
    except StorageError:
        return None


async def _purchase_to_out(
    purchase: Purchase, *, include_download_urls: bool = True
) -> PurchaseOut:
    """Build the response object — total, items, and (optionally) signed
    download URLs for each attached file. Set `include_download_urls=False`
    when responding to a write that just created the purchase with no files."""
    items = [HoldingOut.model_validate(h) for h in purchase.holdings]
    total = sum((h.purchase_price for h in purchase.holdings), Decimal("0"))

    files = [FileOut.model_validate(f) for f in purchase.files]
    if include_download_urls and files:
        urls = await asyncio.gather(*(_signed_url_or_none(f.storage_path) for f in files))
        for out, url in zip(files, urls, strict=True):
            out.download_url = url

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


def _apply_item(holding: Holding, item: HoldingCreate) -> None:
    """Copy a line item's fields onto a holding; weight_grams is always derived."""
    for field in (
        "metal",
        "purity",
        "form",
        "weight_value",
        "weight_unit",
        "quantity",
        "brand",
        "purchase_price",
        "spot_rate_at_purchase",
        "premium_paid",
        "storage_location",
        "comments",
    ):
        setattr(holding, field, getattr(item, field))
    holding.weight_grams = to_grams(item.weight_value, item.weight_unit)


async def _load_full(session: AsyncSession, purchase_id: UUID) -> Purchase:
    stmt = select(Purchase).where(Purchase.id == purchase_id).options(*_FULL_PURCHASE)
    return (await session.execute(stmt)).scalar_one()


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
        **{f: getattr(body, f) for f in _PURCHASE_FIELDS},
    )
    session.add(purchase)
    await session.flush()  # populate purchase.id

    for item in body.items:
        holding = Holding(purchase_id=purchase.id)
        _apply_item(holding, item)
        session.add(holding)

    await session.commit()
    return await _purchase_to_out(
        await _load_full(session, purchase.id), include_download_urls=False
    )


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
        .options(*_FULL_PURCHASE)
        .order_by(
            Purchase.purchase_date.desc(),
            Purchase.created_at.desc(),
        )
    )
    purchases = (await session.execute(stmt)).scalars().all()
    out = await asyncio.gather(*(_purchase_to_out(p) for p in purchases))
    return PurchaseListResponse(purchases=list(out))


@router.get("/purchases/{purchase_id}", response_model=PurchaseOut)
async def get_purchase(purchase: OwnedPurchaseDep, session: SessionDep) -> PurchaseOut:
    return await _purchase_to_out(await _load_full(session, purchase.id))


@router.put("/purchases/{purchase_id}", response_model=PurchaseOut)
async def update_purchase(
    body: PurchaseUpdate,
    purchase: OwnedPurchaseDep,
    session: SessionDep,
) -> PurchaseOut:
    """Replace a purchase's details and line items in one transaction.

    Items with an `id` are updated, items without one are added, and
    existing items missing from the list are removed. A sold item can't be
    removed — undo its sale first, so a sale record is never lost silently.
    """
    purchase = await _load_full(session, purchase.id)
    existing = {h.id: h for h in purchase.holdings}

    sent_ids = [item.id for item in body.items if item.id is not None]
    unknown = set(sent_ids) - existing.keys()
    if unknown or len(sent_ids) != len(set(sent_ids)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Items reference unknown or duplicate ids for this purchase.",
        )
    removed = [h for hid, h in existing.items() if hid not in set(sent_ids)]
    if any(h.status == "sold" for h in removed):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A sold item can't be removed. Undo its sale first.",
        )

    for field in _PURCHASE_FIELDS:
        setattr(purchase, field, getattr(body, field))
    for h in removed:
        await session.delete(h)
    for item in body.items:
        if item.id is None:
            holding = Holding(purchase_id=purchase.id)
            session.add(holding)
        else:
            holding = existing[item.id]
        _apply_item(holding, item)

    await session.commit()
    session.expunge_all()  # drop stale collections before re-reading
    return await _purchase_to_out(await _load_full(session, purchase.id))


@router.delete("/purchases/{purchase_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_purchase(purchase: OwnedPurchaseDep, session: SessionDep) -> None:
    """Delete a purchase with its items, sales and receipts.

    Receipt objects go first — if Storage fails we keep the DB rows so the
    user can retry, rather than orphaning bytes. Rows below the purchase are
    removed by the database's ON DELETE CASCADE.
    """
    stmt = select(UploadedFile.storage_path).where(UploadedFile.purchase_id == purchase.id)
    paths = list((await session.execute(stmt)).scalars())
    try:
        await delete_objects(paths)
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Storage error: {exc}",
        ) from exc

    await session.execute(delete(Purchase).where(Purchase.id == purchase.id))
    await session.commit()

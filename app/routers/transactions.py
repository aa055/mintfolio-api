from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_session
from app.models.holding import Holding
from app.models.purchase import Purchase
from app.schemas.transaction import TransactionListOut, TransactionOut
from app.services.portfolio_access import OwnedPortfolioDep

router = APIRouter(tags=["transactions"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def holding_label(h: Holding) -> str:
    """'Gold 24K bar' — metal, then purity and form when known."""
    return " ".join(part for part in (h.metal.capitalize(), h.purity, h.form) if part)


def _items_summary(holdings: list[Holding]) -> str:
    if not holdings:
        return ""
    first = holding_label(holdings[0])
    more = len(holdings) - 1
    return f"{first} + {more} more" if more else first


@router.get("/portfolios/{portfolio_id}/transactions", response_model=TransactionListOut)
async def list_transactions(
    portfolio: OwnedPortfolioDep,
    session: SessionDep,
    kind: Annotated[Literal["all", "purchase", "sale"], Query(alias="type")] = "all",
    since: date | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> TransactionListOut:
    """Purchases and sales in one feed, newest first.

    `since` keeps rows dated on or after that day (purchase date for
    purchases, sale date for sales).
    """
    stmt = (
        select(Purchase)
        .where(Purchase.portfolio_id == portfolio.id)
        .options(
            selectinload(Purchase.holdings).selectinload(Holding.sale),
            selectinload(Purchase.files),
        )
    )
    purchases = (await session.execute(stmt)).scalars().all()

    rows: list[TransactionOut] = []
    for p in purchases:
        holdings = sorted(p.holdings, key=lambda h: h.created_at)
        if kind in ("all", "purchase"):
            rows.append(
                TransactionOut(
                    kind="purchase",
                    date=p.purchase_date,
                    created_at=p.created_at,
                    purchase_id=p.id,
                    holding_id=None,
                    title=p.dealer or "Unknown dealer",
                    detail=_items_summary(holdings),
                    currency=p.purchase_currency,
                    amount=sum((h.purchase_price for h in holdings), Decimal(0)),
                    realized_pl=None,
                    item_count=len(holdings),
                    receipt_count=len(p.files),
                    metals=sorted({h.metal for h in holdings}),
                )
            )
        if kind in ("all", "sale"):
            for h in holdings:
                sale = h.sale
                if sale is None:
                    continue
                same_currency = sale.sale_currency == p.purchase_currency
                rows.append(
                    TransactionOut(
                        kind="sale",
                        date=sale.sale_date,
                        created_at=sale.created_at,
                        purchase_id=p.id,
                        holding_id=h.id,
                        title=holding_label(h),
                        detail=sale.sold_to or "",
                        currency=sale.sale_currency,
                        amount=sale.sale_price,
                        realized_pl=(
                            sale.sale_price - h.purchase_price - sale.fees
                            if same_currency
                            else None
                        ),
                        item_count=1,
                        receipt_count=0,
                        metals=[h.metal],
                    )
                )

    if since is not None:
        rows = [r for r in rows if r.date >= since]
    rows.sort(key=lambda r: (r.date, r.created_at), reverse=True)
    return TransactionListOut(transactions=rows[:limit])

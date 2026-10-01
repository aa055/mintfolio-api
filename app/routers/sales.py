from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models.sale import Sale
from app.schemas.purchase import HoldingOut, SaleCreate
from app.services.portfolio_access import OwnedHoldingDep

router = APIRouter(tags=["sales"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.post(
    "/holdings/{holding_id}/sale",
    response_model=HoldingOut,
    status_code=status.HTTP_201_CREATED,
)
async def sell_holding(
    body: SaleCreate,
    holding: OwnedHoldingDep,
    session: SessionDep,
) -> HoldingOut:
    """Record the sale of a whole holding and mark it sold.

    One sale per holding (UNIQUE on sales.holding_id) — partial sales are
    Phase 2. Realized P/L is only computed when the sale currency matches
    the purchase currency; otherwise the sale is recorded but not valued.
    """
    if holding.sale is not None or holding.status == "sold":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This item is already sold. Undo the sale to record a different one.",
        )
    if body.sale_date < holding.purchase.purchase_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Sale date can't be before the purchase date.",
        )

    holding.sale = Sale(holding_id=holding.id, **body.model_dump())
    holding.status = "sold"
    await session.commit()
    await session.refresh(holding, attribute_names=["sale", "updated_at"])
    return HoldingOut.model_validate(holding)


@router.delete("/holdings/{holding_id}/sale", status_code=status.HTTP_204_NO_CONTENT)
async def undo_sale(holding: OwnedHoldingDep, session: SessionDep) -> None:
    """Delete the sale record and return the holding to active."""
    if holding.sale is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This item has no sale to undo.",
        )
    await session.delete(holding.sale)
    holding.status = "active"
    await session.commit()

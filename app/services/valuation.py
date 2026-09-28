"""Portfolio valuation — current value, unrealized and realized P/L.

Formulas follow docs/schema-design.md ("Math sanity check"). One deviation
in *how* the rate is found: rather than matching a `price_history` row by
purity label, we take the pure (24K / 999) gram rate and scale it by the
holding's purity fraction. GoldAPI's karat prices are exactly
`24K × k/24`, so the result is identical for stored purities — and it also
values purities GoldAPI doesn't list (916, 999.9, 925, ...).

Currency: totals are in the user's preferred currency. Holdings bought in
another currency are left out of totals (FX is Phase 2) and counted in
`other_currency_count` so the UI can say so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.holding import Holding
from app.models.price_history import PriceHistory
from app.models.purchase import Purchase
from app.models.user import User

# The purity label the pure rate is stored under, per metal.
PURE_PURITY = {"gold": "24K", "silver": "999"}

CENT = Decimal("0.01")


def purity_fraction(purity: str | None) -> Decimal | None:
    """Parse a free-text purity into a fraction of pure metal.

    '22K' -> 22/24, '999' -> 0.999, '999.9' / '9999' -> 0.9999, '0.925' -> 0.925.
    Unspecified purity is treated as pure — nearly all bullion is .999+.
    Returns None when the text can't be interpreted.
    """
    if purity is None or not purity.strip():
        return Decimal(1)
    s = purity.strip().upper().replace(" ", "")
    for suffix in ("KT", "K"):
        if s.endswith(suffix):
            try:
                karat = Decimal(s[: -len(suffix)])
            except InvalidOperation:
                return None
            return karat / 24 if 0 < karat <= 24 else None
    try:
        d = Decimal(s.rstrip("%"))
    except InvalidOperation:
        return None
    if d <= 0:
        return None
    if d <= 1:  # already a fraction: 0.999
        return d
    if d <= 24:  # bare karat: "22"
        return d / 24
    if d <= 100:  # percent: "99.9"
        return d / 100
    if d <= 1000:  # millesimal fineness: "999", "916", "925", "999.9"
        return d / 1000
    if d <= 10000:  # four-nines written without a point: "9999"
        return d / 10000
    return None


@dataclass(frozen=True)
class PureRate:
    rate_per_gram: Decimal
    currency: str
    source: str  # 'goldapi' | 'manual'
    fetched_at: datetime | None


@dataclass(frozen=True)
class HoldingInput:
    id: UUID
    metal: str
    purity: str | None
    weight_grams: Decimal
    quantity: int
    purchase_price: Decimal
    currency: str
    status: str
    sale_price: Decimal | None = None
    sale_currency: str | None = None
    sale_fees: Decimal = Decimal(0)


@dataclass
class HoldingValue:
    id: UUID
    current_value: Decimal | None = None
    unrealized_pl: Decimal | None = None
    realized_pl: Decimal | None = None


@dataclass
class MetalTotals:
    metal: str
    grams: Decimal = Decimal(0)
    current_value: Decimal = Decimal(0)
    cost_basis: Decimal = Decimal(0)


@dataclass
class Summary:
    currency: str
    total_value: Decimal = Decimal(0)
    cost_basis: Decimal = Decimal(0)  # purchase price of valued active holdings
    total_invested: Decimal = Decimal(0)  # all holdings, active + sold
    unrealized_pl: Decimal = Decimal(0)
    realized_pl: Decimal = Decimal(0)
    active_count: int = 0
    sold_count: int = 0
    unvalued_count: int = 0
    other_currency_count: int = 0
    by_metal: dict[str, MetalTotals] = field(default_factory=dict)
    holdings: list[HoldingValue] = field(default_factory=list)

    @property
    def unrealized_pl_pct(self) -> Decimal | None:
        if not self.cost_basis:
            return None
        return (self.unrealized_pl / self.cost_basis * 100).quantize(CENT)


def value_holding(h: HoldingInput, rates: dict[tuple[str, str], PureRate]) -> HoldingValue:
    """Value one holding in its own purchase currency."""
    out = HoldingValue(id=h.id)
    if h.status == "sold":
        if h.sale_price is not None and h.sale_currency == h.currency:
            out.realized_pl = (h.sale_price - h.purchase_price - h.sale_fees).quantize(CENT)
        return out

    rate = rates.get((h.metal, h.currency))
    fraction = purity_fraction(h.purity)
    if rate is None or fraction is None:
        return out
    value = rate.rate_per_gram * fraction * h.weight_grams * h.quantity
    out.current_value = value.quantize(CENT)
    out.unrealized_pl = out.current_value - h.purchase_price
    return out


def summarize(
    holdings: list[HoldingInput],
    currency: str,
    rates: dict[tuple[str, str], PureRate],
) -> Summary:
    summary = Summary(currency=currency)
    for h in holdings:
        hv = value_holding(h, rates)
        summary.holdings.append(hv)

        if h.currency != currency:
            summary.other_currency_count += 1
            continue

        summary.total_invested += h.purchase_price
        if h.status == "sold":
            summary.sold_count += 1
            if hv.realized_pl is not None:
                summary.realized_pl += hv.realized_pl
            continue

        summary.active_count += 1
        metal = summary.by_metal.setdefault(h.metal, MetalTotals(metal=h.metal))
        metal.grams += h.weight_grams * h.quantity
        if hv.current_value is None or hv.unrealized_pl is None:
            summary.unvalued_count += 1
            continue
        summary.total_value += hv.current_value
        summary.cost_basis += h.purchase_price
        summary.unrealized_pl += hv.unrealized_pl
        metal.current_value += hv.current_value
        metal.cost_basis += h.purchase_price
    return summary


# ---------------------------------------------------------------
# DB loaders
# ---------------------------------------------------------------


async def latest_live_rates(session: AsyncSession) -> dict[tuple[str, str], PureRate]:
    """Latest GoldAPI pure rate per (metal, currency)."""
    stmt = (
        select(PriceHistory)
        .where(
            PriceHistory.source == "goldapi",
            or_(
                *(
                    and_(PriceHistory.metal == metal, PriceHistory.purity == purity)
                    for metal, purity in PURE_PURITY.items()
                )
            ),
        )
        .distinct(PriceHistory.metal, PriceHistory.currency)
        .order_by(PriceHistory.metal, PriceHistory.currency, PriceHistory.fetched_at.desc())
    )
    rows = (await session.execute(stmt)).scalars().all()
    return {
        (r.metal, r.currency): PureRate(r.rate_per_gram, r.currency, "goldapi", r.fetched_at)
        for r in rows
    }


def manual_rates(user: User) -> dict[tuple[str, str], PureRate]:
    """The user's own pure-metal rates, from their profile."""
    if not user.manual_rates_currency:
        return {}
    cur = user.manual_rates_currency
    rates = {}
    for metal, rate in (
        ("gold", user.manual_gold_rate_per_gram),
        ("silver", user.manual_silver_rate_per_gram),
    ):
        if rate is not None:
            rates[(metal, cur)] = PureRate(rate, cur, "manual", user.updated_at)
    return rates


async def rates_for_user(session: AsyncSession, user: User) -> dict[tuple[str, str], PureRate]:
    if user.default_pricing_mode == "manual":
        return manual_rates(user)
    return await latest_live_rates(session)


async def load_holdings(session: AsyncSession, portfolio_id: UUID) -> list[HoldingInput]:
    stmt = (
        select(Holding, Purchase.purchase_currency)
        .join(Purchase, Holding.purchase_id == Purchase.id)
        .where(Purchase.portfolio_id == portfolio_id)
        .options(selectinload(Holding.sale))
    )
    result = []
    for h, currency in (await session.execute(stmt)).all():
        sale = h.sale
        result.append(
            HoldingInput(
                id=h.id,
                metal=h.metal,
                purity=h.purity,
                weight_grams=h.weight_grams,
                quantity=h.quantity,
                purchase_price=h.purchase_price,
                currency=currency,
                status=h.status,
                sale_price=sale.sale_price if sale else None,
                sale_currency=sale.sale_currency if sale else None,
                sale_fees=sale.fees if sale else Decimal(0),
            )
        )
    return result

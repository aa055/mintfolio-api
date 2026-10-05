"""Portfolio performance over time, from daily market price history.

All inputs are plain data, so the math is unit-testable without a DB:
holdings come from `valuation.load_holdings`, rates from
`price_history.daily_pure_rates` (one pure rate per day, gaps filled).

Like the summary, only holdings bought in the chosen currency count, and
holdings whose purity can't be parsed are left out of both value and
invested, so the gap between the two lines is always a real gain or loss.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from app.services.valuation import CENT, HoldingInput, purity_fraction

# metal -> [(day, pure rate per gram)], ascending and daily-contiguous
RateSeries = dict[str, list[tuple[date, Decimal]]]


@dataclass(frozen=True)
class SeriesPoint:
    day: date
    value: Decimal
    invested: Decimal
    realized: Decimal  # cumulative realized P/L from sales on or before `day`


@dataclass(frozen=True)
class DayChange:
    day: date  # latest price day
    previous_day: date
    amount: Decimal
    pct: Decimal | None


@dataclass(frozen=True)
class MarketRate:
    metal: str
    day: date
    rate_per_gram: Decimal
    previous_day: date | None
    previous_rate: Decimal | None
    change_pct: Decimal | None


def _countable(holdings: list[HoldingInput], currency: str) -> list[tuple[HoldingInput, Decimal]]:
    """Holdings in `currency` with a known purchase date and parseable purity."""
    out = []
    for h in holdings:
        fraction = purity_fraction(h.purity)
        if h.currency == currency and h.purchase_date is not None and fraction is not None:
            out.append((h, fraction))
    return out


def _held_on(h: HoldingInput, day: date) -> bool:
    assert h.purchase_date is not None
    if h.purchase_date > day:
        return False
    # A sold lot counts up to the day before its sale.
    return h.status != "sold" or h.sale_date is None or h.sale_date > day


def _lot_value(rate: Decimal, fraction: Decimal, h: HoldingInput) -> Decimal:
    # Rounded per lot, exactly like valuation.value_holding, so the last
    # point matches the summary's current value to the cent.
    return (rate * fraction * h.weight_grams * h.quantity).quantize(CENT)


def portfolio_series(
    holdings: list[HoldingInput],
    currency: str,
    rates: RateSeries,
    start: date | None = None,
    end: date | None = None,
) -> list[SeriesPoint]:
    """Daily value and invested (cost of what was held that day).

    Starts at the later of `start` and the first purchase. Ends at `end`
    (normally today), carrying the latest prices forward past the last
    price day, so the final point reflects what is held *now* and matches
    the summary even after a purchase or sale made today. Days where a held
    metal has no price are skipped.
    """
    lots = _countable(holdings, currency)
    if not lots:
        return []
    first_purchase = min(h.purchase_date for h, _ in lots if h.purchase_date)
    begin = max(start, first_purchase) if start else first_purchase

    by_day = {metal: dict(series) for metal, series in rates.items()}
    days = sorted({d for series in rates.values() for d, _ in series if d >= begin})
    if days and end and end > days[-1]:
        last = days[-1]
        for metal_rates in by_day.values():
            if last in metal_rates:
                for i in range(1, (end - last).days + 1):
                    metal_rates[last + timedelta(days=i)] = metal_rates[last]
        days += [last + timedelta(days=i) for i in range(1, (end - last).days + 1)]

    # Realized P/L lands on the sale date (only sales in the same currency are valued).
    sales = [
        (h.sale_date, h.sale_price - h.purchase_price - h.sale_fees)
        for h, _ in lots
        if h.status == "sold"
        and h.sale_date is not None
        and h.sale_price is not None
        and h.sale_currency == h.currency
    ]

    points = []
    for day in days:
        value = invested = Decimal(0)
        realized = sum((pl for sold_on, pl in sales if sold_on <= day), Decimal(0))
        complete = True
        for h, fraction in lots:
            if not _held_on(h, day):
                continue
            rate = by_day.get(h.metal, {}).get(day)
            if rate is None:
                complete = False
                break
            value += _lot_value(rate, fraction, h)
            invested += h.purchase_price
        if complete:
            points.append(SeriesPoint(day=day, value=value, invested=invested, realized=realized))
    return points


def day_change(holdings: list[HoldingInput], currency: str, rates: RateSeries) -> DayChange | None:
    """Value change of current holdings between the last two price days.

    Lots bought on the latest day aren't included — they have no
    previous-day value. Returns None without two days of prices.
    """
    days = sorted({d for series in rates.values() for d, _ in series})
    if len(days) < 2:
        return None
    latest, previous = days[-1], days[-2]
    by_day = {metal: dict(series) for metal, series in rates.items()}

    amount = base = Decimal(0)
    for h, fraction in _countable(holdings, currency):
        if h.status == "sold" or not _held_on(h, previous):
            continue
        now = by_day.get(h.metal, {}).get(latest)
        before = by_day.get(h.metal, {}).get(previous)
        if now is None or before is None:
            continue
        amount += _lot_value(now, fraction, h) - _lot_value(before, fraction, h)
        base += _lot_value(before, fraction, h)
    pct = (amount / base * 100).quantize(CENT) if base else None
    return DayChange(day=latest, previous_day=previous, amount=amount, pct=pct)


def market_rates(rates: RateSeries) -> list[MarketRate]:
    """Latest pure rate per metal with its change from the previous day."""
    out = []
    for metal in ("gold", "silver"):
        series = rates.get(metal) or []
        if not series:
            continue
        day, rate = series[-1]
        prev = series[-2] if len(series) > 1 else None
        change = ((rate - prev[1]) / prev[1] * 100).quantize(CENT) if prev and prev[1] else None
        out.append(
            MarketRate(
                metal=metal,
                day=day,
                rate_per_gram=rate,
                previous_day=prev[0] if prev else None,
                previous_rate=prev[1] if prev else None,
                change_pct=change,
            )
        )
    return out

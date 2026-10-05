from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from app.services.performance import day_change, market_rates, portfolio_series
from app.services.valuation import HoldingInput

D = Decimal
D1 = date(2026, 9, 1)


def _days(n: int, start: date = D1) -> list[date]:
    return [start + timedelta(days=i) for i in range(n)]


def _h(**kw: object) -> HoldingInput:
    base: dict[str, object] = dict(
        id=uuid4(),
        metal="gold",
        purity="24K",
        weight_grams=D("10"),
        quantity=1,
        purchase_price=D("4000.00"),
        currency="AED",
        status="active",
        purchase_date=D1,
    )
    base.update(kw)
    return HoldingInput(**base)  # type: ignore[arg-type]


# gold 400, 410, 420, 430, 440 ; silver 5 flat
RATES = {
    "gold": [(d, D(400 + 10 * i)) for i, d in enumerate(_days(5))],
    "silver": [(d, D("5")) for d in _days(5)],
}


def test_series_tracks_value_invested_purchases_and_sales() -> None:
    holdings = [
        _h(),  # 10 g from day 0
        _h(purchase_date=D1 + timedelta(days=2), purchase_price=D("2100.00"), weight_grams=D("5")),
        _h(
            metal="silver",
            purity="999",
            weight_grams=D("100"),
            purchase_price=D("450.00"),
            status="sold",
            sale_date=D1 + timedelta(days=3),
            sale_price=D("520"),
            sale_currency="AED",
        ),
        _h(currency="USD"),  # other currency: excluded
        _h(purity="??"),  # unparseable purity: excluded from value AND invested
    ]
    pts = portfolio_series(holdings, "AED", RATES)
    assert [p.day for p in pts] == _days(5)
    # day 0: gold 10g@400 = 4000 ; silver 100g*.999*5 = 499.50 -> value 4499.50, invested 4450
    assert (pts[0].value, pts[0].invested) == (D("4499.50"), D("4450.00"))
    # day 2: + 5 g bought @420 -> gold 15g*420 = 6300 ; silver still held
    assert (pts[2].value, pts[2].invested) == (D("6799.50"), D("6550.00"))
    # day 3: silver sold that day -> no longer held
    assert (pts[3].value, pts[3].invested) == (D("6450.00"), D("6100.00"))
    # its realized P/L (520 - 450 = +70) counts from the sale day on
    assert [p.realized for p in pts] == [D(0), D(0), D(0), D("70.00"), D("70.00")]


def test_series_respects_start_and_empty_portfolio() -> None:
    pts = portfolio_series([_h()], "AED", RATES, start=D1 + timedelta(days=3))
    assert [p.day for p in pts] == _days(2, D1 + timedelta(days=3))
    assert portfolio_series([], "AED", RATES) == []


def test_day_change_uses_last_two_days_and_skips_new_and_sold_lots() -> None:
    holdings = [
        _h(),  # held: 10g x (440-430) = +100 on base 4300
        _h(purchase_date=D1 + timedelta(days=4)),  # bought on latest day: excluded
        _h(status="sold", sale_date=D1 + timedelta(days=2)),  # sold: excluded
    ]
    change = day_change(holdings, "AED", RATES)
    assert change is not None
    assert (change.day, change.previous_day) == (D1 + timedelta(days=4), D1 + timedelta(days=3))
    assert change.amount == D("100.00")
    assert change.pct == D("2.33")
    assert day_change(holdings, "AED", {"gold": RATES["gold"][:1]}) is None


def test_market_rates_change_pct() -> None:
    rates = market_rates(RATES)
    gold = next(r for r in rates if r.metal == "gold")
    assert (gold.rate_per_gram, gold.previous_rate, gold.change_pct) == (D(440), D(430), D("2.33"))
    silver = next(r for r in rates if r.metal == "silver")
    assert silver.change_pct == D("0.00")
    assert market_rates({}) == []


def test_series_extends_to_today_with_current_holdings() -> None:
    today = D1 + timedelta(days=6)  # two days past the last price day
    holdings = [
        _h(),
        _h(purity="22K", status="sold", sale_date=today, sale_price=D("1"), sale_currency="AED"),
    ]
    pts = portfolio_series(holdings, "AED", RATES, end=today)
    assert pts[-1].day == today
    # last price (440) carried forward; the lot sold today is no longer held
    assert (pts[-1].value, pts[-1].invested) == (D("4400.00"), D("4000.00"))
    # the day before, it was still held
    assert pts[-2].invested == D("8000.00")
    assert portfolio_series(holdings, "AED", RATES, end=D1)[-1].day == D1 + timedelta(days=4)

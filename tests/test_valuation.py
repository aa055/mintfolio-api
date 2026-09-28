from decimal import Decimal
from uuid import uuid4

import pytest

from app.services.valuation import HoldingInput, PureRate, purity_fraction, summarize

D = Decimal


@pytest.mark.parametrize(
    ("purity", "expected"),
    [
        (None, D(1)),
        ("", D(1)),
        ("24K", D(1)),
        ("22k", D(22) / 24),
        ("18 KT", D(18) / 24),
        ("22", D(22) / 24),
        ("999", D("0.999")),
        ("999.9", D("0.9999")),
        ("9999", D("0.9999")),
        ("916", D("0.916")),
        ("925", D("0.925")),
        ("0.925", D("0.925")),
        ("99.9%", D("0.999")),
        ("30K", None),
        ("gold", None),
        ("0", None),
    ],
)
def test_purity_fraction(purity: str | None, expected: Decimal | None) -> None:
    assert purity_fraction(purity) == expected


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
    )
    base.update(kw)
    return HoldingInput(**base)  # type: ignore[arg-type]


RATES = {
    ("gold", "AED"): PureRate(D("500.0000"), "AED", "goldapi", None),
    ("silver", "AED"): PureRate(D("5.0000"), "AED", "goldapi", None),
}


def test_summary_math() -> None:
    holdings = [
        _h(),  # 10g 24K @500 = 5000, cost 4000 -> +1000
        _h(purity="22K", weight_grams=D("12"), quantity=2, purchase_price=D("10000.00")),
        # 12 * 2 * 500 * 22/24 = 11000 -> +1000
        _h(metal="silver", purity="999", weight_grams=D("31.1035"), purchase_price=D("150.00")),
        # 31.1035 * 5 * 0.999 = 155.36 -> +5.36
        _h(
            status="sold",
            purchase_price=D("3000.00"),
            sale_price=D("3500.00"),
            sale_currency="AED",
            sale_fees=D("50.00"),
        ),  # realized +450
        _h(currency="USD"),  # excluded from totals
        _h(purity="unknown"),  # unvalued: counted in invested, not in value
    ]
    s = summarize(holdings, "AED", RATES)

    assert s.total_value == D("16155.36")
    assert s.cost_basis == D("14150.00")
    assert s.unrealized_pl == D("2005.36")
    assert s.unrealized_pl_pct == D("14.17")
    assert s.realized_pl == D("450.00")
    assert s.total_invested == D("21150.00")
    assert (s.active_count, s.sold_count) == (4, 1)
    assert (s.unvalued_count, s.other_currency_count) == (1, 1)
    assert s.by_metal["gold"].grams == D("44")
    assert s.by_metal["silver"].current_value == D("155.36")


def test_missing_rate_leaves_holding_unvalued() -> None:
    s = summarize([_h(metal="silver", purity="999")], "AED", {})
    assert s.unvalued_count == 1
    assert s.total_value == 0
    assert s.unrealized_pl_pct is None
    assert s.holdings[0].current_value is None

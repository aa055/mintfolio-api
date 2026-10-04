from datetime import date, timedelta
from decimal import Decimal

from app.jobs.backfill_prices import WINDOW_DAYS, days_to_fetch, rows_for_day, windows
from app.services.price_history import fill_daily, range_start

D = Decimal


def test_windows_cover_range_without_gaps_or_overlap() -> None:
    start, end = date(2021, 9, 30), date(2026, 9, 30)
    ws = windows(start, end)
    assert ws[0][0] == start and ws[-1][1] == end
    assert all((b - a).days + 1 <= WINDOW_DAYS for a, b in ws)
    assert all(ws[i][1] + timedelta(days=1) == ws[i + 1][0] for i in range(len(ws) - 1))
    assert len(ws) == 61


def test_single_day_window() -> None:
    d = date(2026, 9, 30)
    assert windows(d, d) == [(d, d)]


def test_rows_for_day_converts_usd_per_troy_ounce_to_pegged_per_gram() -> None:
    rows = rows_for_day(
        date(2026, 9, 29), {"gold": 4181.985, "silver": 61.473, "platinum": 1}, ["AED", "USD"]
    )
    by_key = {(r["metal"], r["currency"]): r for r in rows}
    assert set(by_key) == {("gold", "AED"), ("gold", "USD"), ("silver", "AED"), ("silver", "USD")}
    # 4181.985 / 31.1035 = 134.45382 USD/g ; x 3.6725 = 493.7817 AED/g
    assert by_key[("gold", "USD")]["rate_per_gram"] == D("134.4538")
    assert by_key[("gold", "AED")]["rate_per_gram"] == D("493.7817")
    assert by_key[("gold", "AED")]["purity"] == "24K"
    assert by_key[("silver", "AED")]["purity"] == "999"
    assert all(r["source"] == "metalsdev" and r["user_id"] is None for r in rows)


def test_rows_for_day_skips_missing_metal() -> None:
    rows = rows_for_day(date(2026, 9, 29), {"gold": 4000.0}, ["AED"])
    assert [r["metal"] for r in rows] == ["gold"]


def test_fill_daily_carries_forward_inside_gaps_only() -> None:
    d = date(2026, 9, 1)
    filled = fill_daily([(d, D("1")), (d + timedelta(days=3), D("2"))])
    assert filled == [
        (d, D("1")),
        (d + timedelta(days=1), D("1")),
        (d + timedelta(days=2), D("1")),
        (d + timedelta(days=3), D("2")),
    ]
    assert fill_daily([]) == []


def test_range_start() -> None:
    today = date(2026, 10, 1)
    assert range_start("ALL", today) is None
    assert range_start("YTD", today) == date(2026, 1, 1)
    assert range_start("1M", today) == date(2026, 9, 1)  # 30 days back
    assert range_start("1Y", today) == date(2025, 10, 1)


def test_days_to_fetch_skips_interior_provider_gaps() -> None:
    start, end = date(2024, 12, 1), date(2025, 1, 10)
    gap = {date(2024, 12, 25), date(2024, 12, 26)}
    stored = {
        start + timedelta(days=i) for i in range((date(2025, 1, 5) - start).days + 1)
    } - gap  # stored through 5 Jan, minus a holiday gap
    expected_new = {date(2025, 1, d) for d in range(6, 11)}
    assert days_to_fetch(start, end, stored, fill_gaps=False) == expected_new
    assert days_to_fetch(start, end, stored, fill_gaps=True) == expected_new | gap
    assert len(days_to_fetch(start, end, set(), fill_gaps=False)) == 41

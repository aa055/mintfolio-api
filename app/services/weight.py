"""Weight unit conversion to canonical grams.

We use the **troy ounce** (31.1035 g) for precious metals — NOT the
avoirdupois ounce (28.3495 g). Tola (used in UAE/India) is a future
addition; not in the MVP unit list.
"""

from decimal import Decimal
from typing import Literal

WeightUnit = Literal["g", "kg", "oz"]

# Decimal so the conversion stays exact at arbitrary precision.
_GRAMS_PER_UNIT: dict[str, Decimal] = {
    "g": Decimal("1"),
    "kg": Decimal("1000"),
    "oz": Decimal("31.1035"),  # troy ounce
}


def to_grams(value: Decimal, unit: WeightUnit) -> Decimal:
    """Convert a (value, unit) pair to canonical grams."""
    factor = _GRAMS_PER_UNIT.get(unit)
    if factor is None:
        raise ValueError(f"Unsupported weight unit: {unit!r}")
    return (value * factor).quantize(Decimal("0.0001"))

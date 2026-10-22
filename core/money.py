"""Money helpers — the single source of truth for PKR formatting.

All money is Decimal(max_digits=12, decimal_places=2), never float.
Everything is quantized with ROUND_HALF_UP through :func:`q2`.
Numbers use international grouping (1,250,000).
"""

from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("0.01")


def q2(value):
    """Quantize any number to 2 decimal places, ROUND_HALF_UP."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def format_rs(value):
    """Rs 1,250,000 — decimals only when they are not zero."""
    value = q2(value)
    if value == value.to_integral_value():
        return f"Rs {value:,.0f}"
    return f"Rs {value:,.2f}"


def format_balance(value):
    """Customer balance: positive means the customer owes; a negative
    balance shows as advance credit, e.g. "Rs 5,000 credit"."""
    value = q2(value)
    if value < 0:
        return f"{format_rs(-value)} credit"
    return format_rs(value)

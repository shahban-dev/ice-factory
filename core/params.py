"""Safe parsing of hand-edited query strings.

Staff can put anything in a URL (?customer=abc, ?from=2026-13-45).
These helpers turn invalid values into "no filter" instead of a 500
page:

- parse_int: digits only, bounded to 32-bit. A 30-digit "id" would
  overflow even a bigint column on PostgreSQL, so it is ignored.
- parse_date: YYYY-MM-DD only, built through the real date
  constructor, so 2026-13-45 and 2026-02-30 are rejected like any
  other garbage.
"""

from datetime import date as date_cls

_INT32_MAX = 2_147_483_647


def parse_int(value, default=None):
    """int(value) or default. Empty, non-numeric and absurdly large
    values all return default."""
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    try:
        number = int(text, 10)
    except ValueError:
        return default
    if abs(number) > _INT32_MAX:
        return default
    return number


def parse_date(value, default=None):
    """date from a YYYY-MM-DD string, or default for anything else."""
    if not value:
        return default
    try:
        year, month, day = (int(part) for part in str(value).split("-"))
        return date_cls(year, month, day)
    except (ValueError, AttributeError):
        return default

"""Excel/CSV formula neutralization. Any text cell starting with = + - or @
gets a leading apostrophe, so a spreadsheet can never run it as a formula.
"""

_FORMULA_STARTS = ("=", "+", "-", "@")


def safe_cell(value):
    if isinstance(value, str) and value[:1] in _FORMULA_STARTS:
        return "'" + value
    return value

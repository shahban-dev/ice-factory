"""Arabic-script text for ReportLab PDFs.

Problem: ReportLab's built-in Helvetica has no Arabic-script glyphs, so
an Urdu name like "احمد آئس سٹور" printed as black boxes. Fix: bundle
Noto Sans Arabic (OFL licence, see core/fonts/README) and shape text
before it reaches the PDF:

- arabic-reshaper joins the letters into their presentation forms,
- python-bidi puts them in visual (right-to-left) order.

Rules for callers:

- NEVER shape a string that contains markup (<b>, <br/>, ...): shape
  each text segment separately, then assemble the markup around it.
  Use para_text() for Paragraph content (it escapes and wraps) and
  shape_text() + font_for() for plain Table cells.
- Latin text is untouched: shaping and the Arabic font apply only to
  strings that actually contain Arabic-script characters.
- If the font files are missing (fresh checkout before the first PDF),
  ensure_fonts() decodes them from the vendored .b64 files — the repo
  cannot carry binary files, so the .b64 files are the committed copy.
  If decoding also fails, everything degrades to Helvetica (boxes
  again, but never a crash).
"""

import base64
import os

from django.conf import settings

try:
    import arabic_reshaper
    from bidi.algorithm import get_display as _bidi_display
    _SHAPING_AVAILABLE = True
except ImportError:  # pragma: no cover - defensive; both are requirements
    _SHAPING_AVAILABLE = False

FONT_NAME = "NotoSansArabic"
FONT_NAME_BOLD = "NotoSansArabic-Bold"
FONTS_DIR = os.path.join(settings.BASE_DIR, "core", "fonts")
_FILES = {
    "NotoSansArabic-Regular.ttf": "NotoSansArabic-Regular.ttf.b64",
    "NotoSansArabic-Bold.ttf": "NotoSansArabic-Bold.ttf.b64",
}
_registered = False


def ensure_fonts():
    """Decode vendored .b64 fonts to .ttf when the .ttf is missing."""
    for ttf_name, b64_name in _FILES.items():
        ttf_path = os.path.join(FONTS_DIR, ttf_name)
        if os.path.exists(ttf_path):
            continue
        b64_path = os.path.join(FONTS_DIR, b64_name)
        if not os.path.exists(b64_path):
            continue
        try:
            with open(b64_path, "rb") as source:
                data = base64.b64decode(source.read())
            with open(ttf_path, "wb") as target:
                target.write(data)
        except (OSError, ValueError):
            continue


def register_fonts():
    """Register the Arabic fonts with ReportLab. Idempotent. Returns
    True when the Arabic font is usable, False otherwise (callers fall
    back to Helvetica)."""
    global _registered
    if _registered:
        return True
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ImportError:  # pragma: no cover
        return False
    ensure_fonts()
    regular = os.path.join(FONTS_DIR, "NotoSansArabic-Regular.ttf")
    bold = os.path.join(FONTS_DIR, "NotoSansArabic-Bold.ttf")
    if not (os.path.exists(regular) and os.path.exists(bold)):
        return False
    try:
        if FONT_NAME not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(FONT_NAME, regular))
        if FONT_NAME_BOLD not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(FONT_NAME_BOLD, bold))
        pdfmetrics.registerFontFamily(
            FONT_NAME, normal=FONT_NAME, bold=FONT_NAME_BOLD,
            italic=FONT_NAME, boldItalic=FONT_NAME_BOLD,
        )
    except Exception:  # noqa: BLE001 - any font problem must not break PDFs
        return False
    _registered = True
    return True


def contains_arabic(text):
    """True when the text has any Arabic-script character (Arabic,
    Arabic Supplement, Arabic Extended-A, or presentation forms)."""
    if not text:
        return False
    for char in str(text):
        code = ord(char)
        if (0x0600 <= code <= 0x06FF or 0x0750 <= code <= 0x077F
                or 0x08A0 <= code <= 0x08FF or 0xFB50 <= code <= 0xFDFF
                or 0xFE70 <= code <= 0xFEFF):
            return True
    return False


def shape_text(text):
    """Shape Arabic-script text into visual order for ReportLab.
    Latin text passes through untouched."""
    if not text or not contains_arabic(text):
        return text
    if not _SHAPING_AVAILABLE:
        return text
    return _bidi_display(arabic_reshaper.reshape(str(text)))


def font_for(text, bold=False):
    """Font name for a Table cell: the Arabic font for Arabic-script
    text (when registered), Helvetica otherwise."""
    if contains_arabic(text) and register_fonts():
        return FONT_NAME_BOLD if bold else FONT_NAME
    return "Helvetica-Bold" if bold else "Helvetica"


def para_text(text):
    """Escape, shape and (for Arabic text) font-wrap a segment for use
    inside a ReportLab Paragraph. The caller adds its own <b> or <br/>
    markup around the returned segment."""
    from xml.sax.saxutils import escape

    if text is None:
        return ""
    text = str(text)
    shaped = shape_text(text)
    escaped = escape(shaped)
    if contains_arabic(text) and register_fonts():
        return f'<font name="{FONT_NAME}">{escaped}</font>'
    return escaped

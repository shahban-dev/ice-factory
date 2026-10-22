"""WhatsApp helpers (no API, no account needed): wa.me links with a
prefilled message, opened in the browser. Only Pakistani mobiles
(03XX-XXXXXXX) get a link — a landline cannot receive WhatsApp, and
no message is ever sent automatically: the user reviews and sends it
from their own WhatsApp."""

import re
from urllib.parse import quote

from core.money import format_rs


def wa_number(phone):
    """03XX-XXXXXXX -> 923XXXXXXXXX, or None when the number is not
    a Pakistani mobile."""
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("0"):
        digits = "92" + digits[1:]
    if len(digits) == 12 and digits.startswith("923"):
        return digits
    return None


def whatsapp_url(phone, message):
    """Full wa.me link, or None when the number cannot take WhatsApp."""
    number = wa_number(phone)
    if number is None:
        return None
    return f"https://wa.me/{number}?text={quote(message)}"


def invoice_message(factory_name, sale, remaining):
    text = (
        f"Invoice {sale.invoice_number} from {factory_name}: "
        f"total {format_rs(sale.total)}, "
        f"received {format_rs(sale.paid_with_sale)}."
    )
    if remaining is not None:
        text += f" Remaining on this invoice: {format_rs(remaining)}."
    return text


def dues_message(factory_name, customer_name, balance):
    return (
        f"Assalam-o-Alaikum {customer_name}, your outstanding balance "
        f"at {factory_name} is {format_rs(balance)}. "
        "Please arrange payment at your earliest convenience. Thank you."
    )

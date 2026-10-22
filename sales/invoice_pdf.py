"""Printable invoice PDF (ReportLab).

Contents, per the spec: factory name, address, phone, logo, optional tax
registration line, invoice number, date, customer (walk-in shows
"Walk-in / Cash"), items, subtotal, discount, total, amount received
with this sale, remaining on this invoice at issue, the customer's total
outstanding balance at the time of printing, and a print timestamp.
A deleted sale's invoice shows CANCELLED.
"""

import io
import os

from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from core.models import get_settings
from core.money import format_rs
from core.pdf_text import contains_arabic, font_for, para_text, shape_text

LOGO_PATH = os.path.join(settings.BASE_DIR, "static", "icons", "icon-192.png")


def _cancelled_canvas(canvas, doc):
    if doc._cancelled:
        canvas.saveState()
        canvas.setFont("Helvetica-Bold", 60)
        canvas.setFillColorRGB(0.85, 0.15, 0.15)
        canvas.translate(A4[0] / 2, A4[1] / 2)
        canvas.rotate(45)
        canvas.drawCentredString(0, 0, "CANCELLED")
        canvas.restoreState()
    canvas.saveState()
    canvas.setFont("Helvetica", 9)
    canvas.drawCentredString(A4[0] / 2, 12 * mm, "Thank you for your business.")
    canvas.restoreState()


def invoice_pdf_response(sale, remaining, outstanding):
    buffer = io.BytesIO()
    factory = get_settings()
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=15 * mm, bottomMargin=18 * mm,
        title=f"Invoice {sale.invoice_number}",
    )
    doc._cancelled = sale.is_deleted
    story = []

    header_cells = []
    if os.path.exists(LOGO_PATH):
        header_cells.append(Image(LOGO_PATH, width=18 * mm, height=18 * mm))
    else:
        header_cells.append(Paragraph("", styles["Normal"]))
    factory_lines = [f"<b>{para_text(factory.factory_name)}</b>"]
    if factory.address:
        factory_lines.append(para_text(factory.address))
    if factory.phone:
        factory_lines.append(para_text(factory.phone))
    if factory.tax_registration_line:
        factory_lines.append(para_text(factory.tax_registration_line))
    header_cells.append(Paragraph("<br/>".join(factory_lines), styles["Normal"]))
    header = Table([header_cells], colWidths=[22 * mm, 140 * mm])
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(header)
    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph(
        "<b>INVOICE</b>" + (" — CANCELLED" if sale.is_deleted else ""),
        styles["Heading1"],
    ))
    customer_name = (
        shape_text(sale.customer.name) if sale.customer else "Walk-in / Cash"
    )
    meta = Table([
        ["Invoice number:", sale.invoice_number, "Date:", sale.date.strftime("%d-%m-%Y")],
        ["Customer:", customer_name, "Phone:", sale.customer.phone if sale.customer and sale.customer.phone else "—"],
    ], colWidths=[30 * mm, 55 * mm, 20 * mm, 57 * mm])
    meta.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("FONTNAME", (1, 1), (1, 1), font_for(customer_name)),
    ]))
    story.append(meta)
    story.append(Spacer(1, 4 * mm))

    data = [["Product", "Qty", "Unit price", "Line total"]]
    items = list(sale.items.all())
    for item in items:
        data.append([
            shape_text(item.product.name),
            str(item.quantity),
            format_rs(item.unit_price),
            format_rs(item.line_total),
        ])
    items_table = Table(data, colWidths=[75 * mm, 20 * mm, 32 * mm, 35 * mm])
    items_style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f766e")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
    ]
    for row_no, item in enumerate(items, start=1):
        if contains_arabic(item.product.name):
            items_style.append(
                ("FONTNAME", (0, row_no), (0, row_no),
                 font_for(item.product.name))
            )
    items_table.setStyle(TableStyle(items_style))
    story.append(items_table)
    story.append(Spacer(1, 4 * mm))

    totals = [
        ["Subtotal:", format_rs(sale.subtotal)],
        ["Discount:", format_rs(sale.discount)],
        ["Total:", format_rs(sale.total)],
        ["Received with this sale:", format_rs(sale.paid_with_sale)],
    ]
    if remaining is not None:
        totals.append(["Remaining on this invoice:", format_rs(remaining)])
    if outstanding is not None:
        totals.append(["Customer's total outstanding:", format_rs(outstanding)])
    totals_table = Table(totals, colWidths=[110 * mm, 52 * mm])
    totals_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("LINEABOVE", (0, 2), (-1, 2), 1, colors.black),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(totals_table)
    if sale.notes:
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph(f"Notes: {para_text(sale.notes)}", styles["Normal"]))
    if factory.invoice_footer_note:
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph(para_text(factory.invoice_footer_note), styles["Normal"]))
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(
        f"Printed on {timezone.localtime(timezone.now()).strftime('%d-%m-%Y %H:%M')}",
        styles["Normal"],
    ))
    doc.build(story, onFirstPage=_cancelled_canvas, onLaterPages=_cancelled_canvas)
    buffer.seek(0)
    response = HttpResponse(buffer, content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="{sale.invoice_number}.pdf"'
    )
    return response

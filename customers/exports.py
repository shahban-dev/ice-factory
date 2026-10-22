"""Customer ledger exports: PDF (ReportLab) and Excel (openpyxl).

Excel text cells are neutralized against formula injection (see
core/excel.py). Money is written as numbers so the customer can total
the sheet themselves.
"""

import io

from django.http import HttpResponse
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Font
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from core.excel import safe_cell
from core.models import get_settings
from core.money import format_rs


def _period_label(date_from, date_to):
    def fmt(value):
        return value.strftime("%d-%m-%Y") if value else "…"

    if not date_from and not date_to:
        return "All dates"
    return f"{fmt(date_from)} to {fmt(date_to)}"


def ledger_pdf_response(customer, rows, date_from, date_to):
    buffer = io.BytesIO()
    factory = get_settings()
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
        title=f"Ledger — {customer.name}",
    )
    story = [
        Paragraph(f"<b>{factory.factory_name}</b>", styles["Title"]),
        Paragraph(f"{factory.address}<br/>{factory.phone}", styles["Normal"]),
        Spacer(1, 4 * mm),
        Paragraph(f"<b>Customer ledger — {customer.name}</b>", styles["Heading2"]),
        Paragraph(
            f"Phone: {customer.phone or '—'} &nbsp;|&nbsp; "
            f"Period: {_period_label(date_from, date_to)}",
            styles["Normal"],
        ),
        Spacer(1, 3 * mm),
    ]
    data = [["Date", "Detail", "Amount", "Balance"]]
    for row in rows:
        if row["kind"] == "opening":
            data.append(["—", row["ref"], "—", format_rs(row["balance"])])
        else:
            amount = row["amount"]
            amount_text = format_rs(amount) if amount >= 0 else f"({format_rs(-amount)})"
            data.append([
                row["date"].strftime("%d-%m-%Y"),
                row["ref"],
                amount_text,
                format_rs(row["balance"]),
            ])
    table = Table(data, colWidths=[28 * mm, 70 * mm, 35 * mm, 35 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f766e")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
    ]))
    story.append(table)
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(
        f"Printed on {timezone.localtime(timezone.now()).strftime('%d-%m-%Y %H:%M')}",
        styles["Normal"],
    ))
    doc.build(story)
    buffer.seek(0)
    response = HttpResponse(buffer, content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="ledger-{customer.pk}.pdf"'
    )
    return response


def ledger_excel_response(customer, rows, date_from, date_to):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Ledger"
    sheet.append([safe_cell(f"Customer ledger — {customer.name}")])
    sheet.append([safe_cell(f"Period: {_period_label(date_from, date_to)}")])
    sheet.append([])
    header = ["Date", "Detail", "Amount (Rs)", "Balance (Rs)"]
    sheet.append(header)
    for cell in sheet[4]:
        cell.font = Font(bold=True)
    for row in rows:
        if row["kind"] == "opening":
            sheet.append(["—", safe_cell(row["ref"]), None, float(row["balance"])])
        else:
            sheet.append([
                row["date"].strftime("%d-%m-%Y"),
                safe_cell(row["ref"]),
                float(row["amount"]),
                float(row["balance"]),
            ])
    for col in ("A", "B", "C", "D"):
        sheet.column_dimensions[col].width = 22 if col != "B" else 32
    for row in sheet.iter_rows(min_row=5, min_col=3, max_col=4):
        for cell in row:
            if cell.value is not None:
                cell.number_format = "#,##0.00"
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    response = HttpResponse(
        buffer,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = (
        f'attachment; filename="ledger-{customer.pk}.xlsx"'
    )
    return response

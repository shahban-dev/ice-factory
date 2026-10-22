"""PDF and Excel exports for the four reports. Text cells are neutralized
against formula injection (leading apostrophe for cells starting = + - @).
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
from core.pdf_text import para_text

DEFINITIONS = (
    "Definitions: Billed = sum of sale totals by sale date (opening balances "
    "NOT billed). Collected = sum of payments by payment date (incl. toward "
    "opening balances). Expenses = sum of expenses by expense date incl. "
    "salary payments. Sales profit = Billed - Expenses. Cash profit = "
    "Collected - Expenses. Customer balance = opening_balance + sale totals "
    "- payments (positive = owes, negative = advance credit)."
)


def _pdf_response(title, filename, story_bits):
    buffer = io.BytesIO()
    factory = get_settings()
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
        title=title,
    )
    story = [
        Paragraph(f"<b>{para_text(factory.factory_name)}</b>", styles["Title"]),
        Paragraph(
            f"{para_text(factory.address)}<br/>{para_text(factory.phone)}",
            styles["Normal"],
        ),
        Spacer(1, 5 * mm),
        Paragraph(f"<b>{para_text(title)}</b>", styles["Heading1"]),
    ]
    story.extend(story_bits)
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(DEFINITIONS, styles["Normal"]))
    story.append(Paragraph(
        f"Printed on {timezone.localtime(timezone.now()).strftime('%d-%m-%Y %H:%M')}",
        styles["Normal"],
    ))
    doc.build(story)
    buffer.seek(0)
    response = HttpResponse(buffer, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _table(headers, rows):
    styles = getSampleStyleSheet()
    data = [[Paragraph(f"<b>{h}</b>", styles["Normal"]) for h in headers]]
    for row in rows:
        # para_text shapes Arabic-script cells (customer/product names)
        # and escapes everything, so a stray "&" can no longer break the
        # Paragraph parser. Latin cells pass through unchanged.
        data.append([Paragraph(para_text(str(c)), styles["Normal"]) for c in row])
    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def _excel_response(filename, headers, rows):
    wb = Workbook()
    ws = wb.active
    ws.append([safe_cell(h) for h in headers])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for row in rows:
        ws.append([safe_cell(c) for c in row])
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    response = HttpResponse(
        buffer,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def monthly_pdf(data):
    styles = getSampleStyleSheet()
    bits = [
        Paragraph(
            f"{data['month_name']} {data['year']} "
            f"({data['first']:%d-%m-%Y} to {data['last']:%d-%m-%Y})",
            styles["Normal"]),
        Spacer(1, 4 * mm),
        _table(["Measure", "Amount"], [
            ["Billed", format_rs(data["billed"])],
            ["Collected", format_rs(data["collected"])],
            ["Expenses", format_rs(data["expenses"])],
            ["Salaries paid", format_rs(data["salaries_paid"])],
            ["Sales profit", format_rs(data["sales_profit"])],
            ["Cash profit", format_rs(data["cash_profit"])],
            ["Outstanding at month end", format_rs(data["outstanding_at_month_end"])],
        ]),
        Spacer(1, 4 * mm),
        Paragraph("<b>Expenses by category</b>", styles["Heading2"]),
        _table(["Category", "Amount"], [
            [r["category__name"], format_rs(r["total"])] for r in data["by_category"]
        ]),
        Spacer(1, 4 * mm),
        Paragraph("<b>Blocks sold per product</b>", styles["Heading2"]),
        _table(["Product", "Blocks"], [
            [r["product__name"], r["qty"]] for r in data["blocks"]
        ]),
        Spacer(1, 4 * mm),
        Paragraph("<b>Top 10 customers by billed</b>", styles["Heading2"]),
        _table(["Customer", "Billed"], [
            [r["customer__name"], format_rs(r["total"])]
            for r in data["top_customers"]
        ]),
    ]
    return _pdf_response(
        f"Monthly report — {data['month_name']} {data['year']}",
        f"monthly-{data['year']}-{data['month']:02d}.pdf", bits)


def monthly_excel(data):
    rows = [
        ["Billed", float(data["billed"])],
        ["Collected", float(data["collected"])],
        ["Expenses", float(data["expenses"])],
        ["Salaries paid", float(data["salaries_paid"])],
        ["Sales profit", float(data["sales_profit"])],
        ["Cash profit", float(data["cash_profit"])],
        ["Outstanding at month end", float(data["outstanding_at_month_end"])],
        [],
        ["Expenses by category", ""],
    ]
    rows.extend([[r["category__name"], float(r["total"])] for r in data["by_category"]])
    rows.append([])
    rows.append(["Blocks sold per product", ""])
    rows.extend([[r["product__name"], r["qty"]] for r in data["blocks"]])
    rows.append([])
    rows.append(["Top 10 customers by billed", ""])
    rows.extend([[r["customer__name"], float(r["total"])] for r in data["top_customers"]])
    return _excel_response(
        f"monthly-{data['year']}-{data['month']:02d}.xlsx",
        ["Measure", "Amount"], rows)


def dues_pdf(rows):
    styles = getSampleStyleSheet()
    bits = [_table(["Customer", "Balance", "Oldest unpaid invoice", "Last payment"], [
        [
            r["customer"].name,
            format_rs(r["balance"]),
            r["oldest_unpaid"].strftime("%d-%m-%Y") if r["oldest_unpaid"] else "—",
            r["last_payment"].strftime("%d-%m-%Y") if r["last_payment"] else "—",
        ] for r in rows
    ])]
    return _pdf_response("Customer dues report", "dues.pdf", bits)


def dues_excel(rows):
    return _excel_response("dues.xlsx",
        ["Customer", "Balance", "Oldest unpaid invoice", "Last payment"],
        [[
            r["customer"].name,
            float(r["balance"]),
            r["oldest_unpaid"].strftime("%d-%m-%Y") if r["oldest_unpaid"] else "",
            r["last_payment"].strftime("%d-%m-%Y") if r["last_payment"] else "",
        ] for r in rows])


def register_pdf(sales, date_from, date_to):
    bits = [_table(["Date", "Invoice", "Customer", "Items", "Total"], [
        [
            s.date.strftime("%d-%m-%Y"),
            s.invoice_number,
            s.customer.name if s.customer else "Walk-in",
            "; ".join(f"{i.quantity} × {i.product.name}" for i in s.items.all()),
            format_rs(s.total),
        ] for s in sales
    ])]
    return _pdf_response(
        f"Sales register — {date_from:%d-%m-%Y} to {date_to:%d-%m-%Y}",
        "sales-register.pdf", bits)


def register_excel(sales, date_from, date_to):
    return _excel_response("sales-register.xlsx",
        ["Date", "Invoice", "Customer", "Items", "Total"],
        [[
            s.date.strftime("%d-%m-%Y"),
            s.invoice_number,
            s.customer.name if s.customer else "Walk-in",
            "; ".join(f"{i.quantity} × {i.product.name}" for i in s.items.all()),
            float(s.total),
        ] for s in sales])


def expense_pdf(data, date_from, date_to):
    bits = [
        _table(["Date", "Category", "Description", "Method", "Amount"], [
            [
                e.date.strftime("%d-%m-%Y"),
                e.category.name,
                e.description or "—",
                e.get_method_display(),
                format_rs(e.amount),
            ] for e in data["expenses"]
        ]),
        Spacer(1, 4 * mm),
        Paragraph("<b>Totals by category</b>", getSampleStyleSheet()["Heading2"]),
        _table(["Category", "Amount"], [
            [r["category__name"], format_rs(r["total"])] for r in data["by_category"]
        ]),
        Spacer(1, 4 * mm),
        Paragraph(f"<b>Grand total: {format_rs(data['grand'])}</b>",
                  getSampleStyleSheet()["Normal"]),
    ]
    return _pdf_response(
        f"Expense report — {date_from:%d-%m-%Y} to {date_to:%d-%m-%Y}",
        "expense-report.pdf", bits)


def expense_excel(data, date_from, date_to):
    rows = [[
        e.date.strftime("%d-%m-%Y"),
        e.category.name,
        e.description or "",
        e.get_method_display(),
        float(e.amount),
    ] for e in data["expenses"]]
    rows.append([])
    rows.append(["Totals by category", ""])
    rows.extend([[r["category__name"], float(r["total"])] for r in data["by_category"]])
    rows.append(["Grand total", float(data["grand"])])
    return _excel_response("expense-report.xlsx",
        ["Date", "Category", "Description", "Method", "Amount"], rows)

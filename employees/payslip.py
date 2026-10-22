"""Payslip PDF (ReportLab): employee, month, days employed, base, bonus,
deductions with note, net, paid date. The CNIC is masked here, as the spec
only allows the full CNIC on the employee detail page.
"""

import calendar
import io

from django.http import HttpResponse
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from core.models import get_settings
from core.money import format_rs
from core.pdf_text import para_text
from employees.models import Payroll


def payslip_pdf_response(payroll):
    buffer = io.BytesIO()
    factory = get_settings()
    employee = payroll.employee
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
        title=f"Payslip — {employee.name} — {payroll.month:02d}/{payroll.year}",
    )
    month_name = calendar.month_name[payroll.month]
    paid_text = (
        payroll.paid_date.strftime("%d-%m-%Y")
        if payroll.paid_date else "Not paid yet"
    )
    story = [
        Paragraph(f"<b>{para_text(factory.factory_name)}</b>", styles["Title"]),
        Paragraph(
            f"{para_text(factory.address)}<br/>{para_text(factory.phone)}",
            styles["Normal"],
        ),
        Spacer(1, 5 * mm),
        Paragraph("<b>PAYSLIP</b>", styles["Heading1"]),
        Paragraph(
            f"Employee: {para_text(employee.name)}<br/>"
            f"CNIC: {employee.masked_cnic}<br/>"
            f"Role: {employee.get_role_display()}<br/>"
            f"Month: {month_name} {payroll.year}",
            styles["Normal"],
        ),
        Spacer(1, 4 * mm),
    ]
    data = [
        ["Days employed:", str(payroll.days_employed)],
        ["Base salary:", format_rs(payroll.base_salary)],
        ["Bonus:", format_rs(payroll.bonus)],
        ["Deductions:", format_rs(payroll.deductions)],
    ]
    if payroll.loan_id is not None:
        data.append([
            "Loan deduction:",
            f"{format_rs(payroll.loan_deduction)} (loan of "
            f"{format_rs(payroll.loan.amount)} from "
            f"{payroll.loan.date.strftime('%d-%m-%Y')})",
        ])
    data += [
        ["Net salary:", format_rs(payroll.net_salary)],
        ["Paid date:", paid_text],
        ["Status:", payroll.get_status_display()],
    ]
    if payroll.paid_amount is not None:
        data.append(
            ["Amount actually paid:", format_rs(payroll.paid_amount)])
    net_row = next(i for i, row in enumerate(data) if row[0] == "Net salary:")
    table = Table(data, colWidths=[55 * mm, 107 * mm])
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("LINEABOVE", (0, net_row), (-1, net_row), 1, colors.black),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(table)
    if payroll.deduction_note:
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph(
            f"Deduction note: {para_text(payroll.deduction_note)}",
            styles["Normal"]))
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(
        f"Printed on {timezone.localtime(timezone.now()).strftime('%d-%m-%Y %H:%M')}",
        styles["Normal"],
    ))
    doc.build(story)
    buffer.seek(0)
    response = HttpResponse(buffer, content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="payslip-{employee.pk}-{payroll.year}-{payroll.month:02d}.pdf"'
    )
    return response

"""Employee and payroll views."""

import calendar
from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import ListView

from core.params import parse_int
from core.permissions import PermissionRequiredMixin
from core.services import ConcurrentEditError, save_form_with_version, soft_delete_objects
from employees.forms import (
    EmployeeForm,
    LoanForm,
    MarkPaidForm,
    PayrollEditForm,
    PayrollGenerateForm,
)
from employees.models import Employee, Loan, Payroll
from employees.services import (
    create_loan,
    delete_loan,
    generate_payroll,
    loan_remaining,
    loan_repaid,
    mark_paid,
    reopen_payroll,
    update_loan,
    update_payroll_draft,
)


class EmployeeListView(PermissionRequiredMixin, ListView):
    permission_code = "employees.view"
    model = Employee
    template_name = "employees/employee_list.html"
    context_object_name = "employees"
    paginate_by = 25

    def get_queryset(self):
        qs = Employee.objects.all()
        status = self.request.GET.get("status", "")
        if status == "active":
            qs = qs.filter(is_active=True)
        elif status == "inactive":
            qs = qs.filter(is_active=False)
        return qs.order_by("name")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["status"] = self.request.GET.get("status", "")
        return context


class EmployeeDetailView(PermissionRequiredMixin, View):
    permission_code = "employees.view"

    def get(self, request, pk):
        employee = get_object_or_404(Employee, pk=pk)
        payrolls = employee.payrolls.all().order_by("-year", "-month")
        loans = employee.loans.all().order_by("date", "id")
        loan_rows = [
            {
                "loan": loan,
                "repaid": loan_repaid(loan),
                "remaining": loan_remaining(loan),
            }
            for loan in loans
        ]
        loans_outstanding = sum(
            (row["remaining"] for row in loan_rows), Decimal("0")
        )
        return render(request, "employees/employee_detail.html", {
            "employee": employee, "payrolls": payrolls,
            "loan_rows": loan_rows,
            "loans_outstanding": loans_outstanding,
        })


class EmployeeCreateView(PermissionRequiredMixin, View):
    permission_code = "employees.create"

    def get(self, request):
        return render(request, "employees/employee_form.html", {
            "form": EmployeeForm(), "title": "Add employee",
        })

    def post(self, request):
        form = EmployeeForm(request.POST)
        if form.is_valid():
            employee = form.save(commit=False)
            employee.created_by = request.user
            employee.updated_by = request.user
            employee._change_reason = "Created"
            employee.save()
            messages.success(request, f"Employee '{employee.name}' added.")
            return redirect("employees:detail", pk=employee.pk)
        return render(request, "employees/employee_form.html", {
            "form": form, "title": "Add employee",
        })


class EmployeeUpdateView(PermissionRequiredMixin, View):
    permission_code = "employees.edit"

    def get(self, request, pk):
        employee = get_object_or_404(Employee, pk=pk)
        form = EmployeeForm(instance=employee, require_reason=True)
        return render(request, "employees/employee_form.html", {
            "form": form, "title": f"Edit {employee.name}", "employee": employee,
        })

    def post(self, request, pk):
        employee = get_object_or_404(Employee, pk=pk)
        form = EmployeeForm(request.POST, instance=employee, require_reason=True)
        if form.is_valid():
            try:
                saved = save_form_with_version(
                    form, request.user, form.cleaned_data["reason"]
                )
            except ConcurrentEditError as exc:
                form.add_error(None, str(exc))
            else:
                messages.success(request, f"Employee '{saved.name}' updated.")
                return redirect("employees:detail", pk=saved.pk)
        return render(request, "employees/employee_form.html", {
            "form": form, "title": f"Edit {employee.name}", "employee": employee,
        })


class EmployeeDeleteView(PermissionRequiredMixin, View):
    permission_code = "employees.delete"

    def get(self, request, pk):
        employee = get_object_or_404(Employee, pk=pk)
        blocked = employee.payrolls.exists()
        return render(request, "employees/employee_delete.html", {
            "employee": employee, "blocked": blocked,
        })

    def post(self, request, pk):
        employee = get_object_or_404(Employee, pk=pk)
        if request.POST.get("action") == "deactivate":
            if employee.leaving_date is None:
                # Without a leaving date, payroll cannot place this
                # person in any month — so deactivation is refused until
                # the date is set. Otherwise their last partial month
                # would silently never be generated.
                messages.error(
                    request,
                    "Set a leaving date for this employee first, then "
                    "deactivate. Payroll needs the date to generate "
                    "their last partial month.")
                return redirect("employees:edit", pk=employee.pk)
            employee.is_active = False
            employee.updated_by = request.user
            employee._change_reason = "Deactivated instead of deleting"
            employee.save()
            messages.success(request, f"Employee '{employee.name}' deactivated.")
            return redirect("employees:list")
        if employee.payrolls.exists():
            messages.error(
                request,
                "This employee has payroll rows and cannot be deleted. "
                "Deactivate them instead.")
            return redirect("employees:detail", pk=pk)
        soft_delete_objects([employee], request.user, request.POST.get("reason", ""))
        messages.success(request, f"Employee '{employee.name}' deleted.")
        return redirect("employees:list")


class LoanCreateView(PermissionRequiredMixin, View):
    permission_code = "employees.create"

    def get(self, request, pk):
        employee = get_object_or_404(Employee, pk=pk)
        return render(request, "employees/loan_form.html", {
            "form": LoanForm(), "title": f"New loan for {employee.name}",
            "employee": employee,
        })

    def post(self, request, pk):
        employee = get_object_or_404(Employee, pk=pk)
        form = LoanForm(request.POST)
        if form.is_valid():
            try:
                create_loan(
                    request.user, employee,
                    form.cleaned_data["date"],
                    form.cleaned_data["amount"],
                    form.cleaned_data["monthly_installment"],
                    form.cleaned_data["notes"],
                )
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                messages.success(
                    request, f"Loan of Rs {form.cleaned_data['amount']} "
                    f"recorded for {employee.name}.")
                return redirect("employees:detail", pk=employee.pk)
        return render(request, "employees/loan_form.html", {
            "form": form, "title": f"New loan for {employee.name}",
            "employee": employee,
        })


class LoanUpdateView(PermissionRequiredMixin, View):
    permission_code = "employees.edit"

    def get(self, request, pk):
        loan = get_object_or_404(Loan, pk=pk)
        form = LoanForm(instance=loan, require_reason=True)
        return render(request, "employees/loan_form.html", {
            "form": form, "title": f"Edit loan for {loan.employee.name}",
            "employee": loan.employee, "loan": loan,
        })

    def post(self, request, pk):
        loan = get_object_or_404(Loan, pk=pk)
        form = LoanForm(request.POST, instance=loan, require_reason=True)
        if form.is_valid():
            try:
                update_loan(
                    loan, request.user,
                    form.cleaned_data["date"],
                    form.cleaned_data["amount"],
                    form.cleaned_data["monthly_installment"],
                    form.cleaned_data["notes"],
                    form.cleaned_data["reason"],
                    form_version=form.cleaned_data.get("version"),
                )
            except (ValidationError, ConcurrentEditError) as exc:
                form.add_error(None, str(exc) if isinstance(exc, ConcurrentEditError) else exc)
            else:
                messages.success(request, "Loan updated.")
                return redirect("employees:detail", pk=loan.employee_id)
        return render(request, "employees/loan_form.html", {
            "form": form, "title": f"Edit loan for {loan.employee.name}",
            "employee": loan.employee, "loan": loan,
        })


class LoanDeleteView(PermissionRequiredMixin, View):
    permission_code = "employees.delete"

    def get(self, request, pk):
        loan = get_object_or_404(Loan, pk=pk)
        return render(request, "employees/loan_delete.html", {
            "loan": loan, "repaid": loan_repaid(loan),
            "remaining": loan_remaining(loan),
        })

    def post(self, request, pk):
        loan = get_object_or_404(Loan, pk=pk)
        employee_id = loan.employee_id
        try:
            cleared = delete_loan(
                loan, request.user, request.POST.get("reason", ""))
        except ValidationError as exc:
            messages.error(request, str(exc))
            return redirect("employees:detail", pk=employee_id)
        if cleared:
            messages.success(
                request,
                f"Loan deleted. The loan deduction was cleared from "
                f"{len(cleared)} draft payroll row(s).")
        else:
            messages.success(request, "Loan deleted.")
        return redirect("employees:detail", pk=employee_id)


class PayrollListView(PermissionRequiredMixin, ListView):
    permission_code = "payroll.view"
    model = Payroll
    template_name = "employees/payroll_list.html"
    context_object_name = "payrolls"
    paginate_by = 25

    def get_queryset(self):
        qs = Payroll.objects.select_related("employee")
        year = parse_int(self.request.GET.get("year", ""))
        month = parse_int(self.request.GET.get("month", ""))
        employee_id = parse_int(self.request.GET.get("employee", ""))
        status = self.request.GET.get("status", "")
        if year:
            qs = qs.filter(year=year)
        if month:
            qs = qs.filter(month=month)
        if employee_id:
            qs = qs.filter(employee_id=employee_id)
        if status:
            qs = qs.filter(status=status)
        return qs.order_by("-year", "-month", "employee__name")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["employees"] = Employee.objects.all().order_by("name")
        context["year"] = self.request.GET.get("year", "")
        context["month"] = self.request.GET.get("month", "")
        context["selected_employee"] = self.request.GET.get("employee", "")
        context["status"] = self.request.GET.get("status", "")
        context["months"] = [(i, calendar.month_name[i]) for i in range(1, 13)]
        return context


class PayrollDetailView(PermissionRequiredMixin, View):
    permission_code = "payroll.view"

    def get(self, request, pk):
        payroll = get_object_or_404(
            Payroll.objects.select_related("employee", "linked_expense", "loan"), pk=pk
        )
        return render(request, "employees/payroll_detail.html", {
            "payroll": payroll,
            "month_name": calendar.month_name[payroll.month],
        })


class PayrollGenerateView(PermissionRequiredMixin, View):
    permission_code = "payroll.generate"

    def get(self, request):
        return render(request, "employees/payroll_generate.html", {
            "form": PayrollGenerateForm(),
        })

    def post(self, request):
        form = PayrollGenerateForm(request.POST)
        if form.is_valid():
            try:
                result = generate_payroll(
                    request.user,
                    form.cleaned_data["year"],
                    form.cleaned_data["month"],
                )
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                messages.success(
                    request,
                    f"Payroll generated: {result['created']} draft(s) created, "
                    f"{result['skipped_existing']} already existed, "
                    f"{result['skipped_ineligible']} not eligible.")
                if result.get("warnings"):
                    messages.warning(
                        request,
                        "No row for staff with no leaving date: "
                        + ", ".join(result["warnings"])
                        + ". Set their leaving date, then generate again.")
                return redirect(
                    f"/employees/payroll/?year={form.cleaned_data['year']}"
                    f"&month={form.cleaned_data['month']}"
                )
        return render(request, "employees/payroll_generate.html", {"form": form})


class PayrollUpdateView(PermissionRequiredMixin, View):
    permission_code = "payroll.edit"

    def get(self, request, pk):
        payroll = get_object_or_404(Payroll, pk=pk)
        if payroll.status != Payroll.STATUS_DRAFT:
            messages.error(
                request, "This row is already paid. Reopen it first, then edit.")
            return redirect("employees:payroll_detail", pk=pk)
        form = PayrollEditForm(instance=payroll)
        return render(request, "employees/payroll_form.html", {
            "form": form, "payroll": payroll,
            "month_name": calendar.month_name[payroll.month],
        })

    def post(self, request, pk):
        payroll = get_object_or_404(Payroll, pk=pk)
        form = PayrollEditForm(request.POST, instance=payroll)
        if form.is_valid():
            try:
                update_payroll_draft(
                    payroll=payroll,
                    user=request.user,
                    bonus=form.cleaned_data["bonus"] or 0,
                    deductions=form.cleaned_data["deductions"] or 0,
                    deduction_note=form.cleaned_data["deduction_note"],
                    reason=form.cleaned_data["reason"],
                    form_version=form.cleaned_data.get("version"),
                    loan=form.cleaned_data.get("loan"),
                    loan_deduction=form.cleaned_data.get("loan_deduction") or 0,
                )
            except (ValidationError, ConcurrentEditError) as exc:
                form.add_error(None, str(exc) if isinstance(exc, ConcurrentEditError) else exc)
            else:
                messages.success(request, "Payroll row updated.")
                return redirect("employees:payroll_detail", pk=pk)
        return render(request, "employees/payroll_form.html", {
            "form": form, "payroll": payroll,
            "month_name": calendar.month_name[payroll.month],
        })


class PayrollMarkPaidView(PermissionRequiredMixin, View):
    permission_code = "payroll.pay"

    def get(self, request, pk):
        payroll = get_object_or_404(Payroll, pk=pk)
        if payroll.status != Payroll.STATUS_DRAFT:
            messages.error(request, "This row is already paid.")
            return redirect("employees:payroll_detail", pk=pk)
        return render(request, "employees/payroll_pay.html", {
            "form": MarkPaidForm(payroll=payroll), "payroll": payroll,
            "month_name": calendar.month_name[payroll.month],
        })

    def post(self, request, pk):
        payroll = get_object_or_404(Payroll, pk=pk)
        form = MarkPaidForm(request.POST, payroll=payroll)
        if form.is_valid():
            try:
                mark_paid(
                    payroll, request.user, form.cleaned_data["paid_date"],
                    paid_amount=form.cleaned_data.get("paid_amount"),
                    paid_note=form.cleaned_data.get("paid_note", ""),
                )
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                messages.success(
                    request,
                    f"Salary for {payroll.employee.name} marked paid.")
                return redirect("employees:payroll_detail", pk=pk)
        return render(request, "employees/payroll_pay.html", {
            "form": form, "payroll": payroll,
            "month_name": calendar.month_name[payroll.month],
        })


class PayrollReopenView(PermissionRequiredMixin, View):
    permission_code = "payroll.reopen"

    def get(self, request, pk):
        payroll = get_object_or_404(Payroll, pk=pk)
        if payroll.status != Payroll.STATUS_PAID:
            messages.error(request, "Only a paid row can be reopened.")
            return redirect("employees:payroll_detail", pk=pk)
        return render(request, "employees/payroll_reopen.html", {
            "payroll": payroll,
            "month_name": calendar.month_name[payroll.month],
        })

    def post(self, request, pk):
        payroll = get_object_or_404(Payroll, pk=pk)
        try:
            reopen_payroll(payroll, request.user)
        except ValidationError as exc:
            messages.error(request, str(exc))
            return redirect("employees:payroll_detail", pk=pk)
        messages.success(request, "Payroll row reopened as a draft.")
        return redirect("employees:payroll_detail", pk=pk)


class PayslipPdfView(PermissionRequiredMixin, View):
    permission_code = "payroll.view"

    def get(self, request, pk):
        from employees.payslip import payslip_pdf_response

        payroll = get_object_or_404(
            Payroll.objects.select_related("employee", "loan"), pk=pk
        )
        return payslip_pdf_response(payroll)

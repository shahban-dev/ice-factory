"""Employee and payroll views."""

import calendar

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import ListView

from core.permissions import PermissionRequiredMixin
from core.services import ConcurrentEditError, save_form_with_version, soft_delete_objects
from employees.forms import (
    EmployeeForm,
    MarkPaidForm,
    PayrollEditForm,
    PayrollGenerateForm,
)
from employees.models import Employee, Payroll
from employees.services import (
    generate_payroll,
    mark_paid,
    reopen_payroll,
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
        return render(request, "employees/employee_detail.html", {
            "employee": employee, "payrolls": payrolls,
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


class PayrollListView(PermissionRequiredMixin, ListView):
    permission_code = "payroll.view"
    model = Payroll
    template_name = "employees/payroll_list.html"
    context_object_name = "payrolls"
    paginate_by = 25

    def get_queryset(self):
        qs = Payroll.objects.select_related("employee")
        year = self.request.GET.get("year", "")
        month = self.request.GET.get("month", "")
        employee_id = self.request.GET.get("employee", "")
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
        context["employees"] = Employee.objects.filter(is_active=True).order_by("name")
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
            Payroll.objects.select_related("employee", "linked_expense"), pk=pk
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
            "form": MarkPaidForm(), "payroll": payroll,
            "month_name": calendar.month_name[payroll.month],
        })

    def post(self, request, pk):
        payroll = get_object_or_404(Payroll, pk=pk)
        form = MarkPaidForm(request.POST)
        if form.is_valid():
            try:
                mark_paid(
                    payroll, request.user, form.cleaned_data["paid_date"]
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
            Payroll.objects.select_related("employee"), pk=pk
        )
        return payslip_pdf_response(payroll)

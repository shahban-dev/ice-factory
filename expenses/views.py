"""Expense and category views. Payroll-linked expenses are read-only here:
they change only through payroll."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import ListView

from core.params import parse_date, parse_int
from core.permissions import PermissionRequiredMixin
from expenses.forms import ExpenseCategoryForm, ExpenseForm
from expenses.models import Expense, ExpenseCategory
from expenses.services import create_expense, delete_expense, update_expense


class CategoryListView(PermissionRequiredMixin, ListView):
    permission_code = "expenses.view"
    model = ExpenseCategory
    template_name = "expenses/category_list.html"
    context_object_name = "categories"

    def get_queryset(self):
        return ExpenseCategory.objects.all().order_by("name")


class CategoryCreateView(PermissionRequiredMixin, View):
    permission_code = "expenses.create"

    def get(self, request):
        return render(request, "expenses/category_form.html", {
            "form": ExpenseCategoryForm(), "title": "Add category",
        })

    def post(self, request):
        form = ExpenseCategoryForm(request.POST)
        if form.is_valid():
            category = form.save(commit=False)
            category.created_by = request.user
            category.updated_by = request.user
            category._change_reason = "Created"
            category.save()
            messages.success(request, f"Category '{category.name}' added.")
            return redirect("expenses:category_list")
        return render(request, "expenses/category_form.html", {
            "form": form, "title": "Add category",
        })


class CategoryUpdateView(PermissionRequiredMixin, View):
    permission_code = "expenses.edit"

    def get(self, request, pk):
        category = get_object_or_404(ExpenseCategory, pk=pk)
        return render(request, "expenses/category_form.html", {
            "form": ExpenseCategoryForm(instance=category),
            "title": f"Edit {category.name}", "category": category,
        })

    def post(self, request, pk):
        category = get_object_or_404(ExpenseCategory, pk=pk)
        form = ExpenseCategoryForm(request.POST, instance=category)
        if form.is_valid():
            updated = form.save(commit=False)
            updated.updated_by = request.user
            updated._change_reason = request.POST.get("reason", "") or "Edited"
            updated.save()
            messages.success(request, f"Category '{updated.name}' updated.")
            return redirect("expenses:category_list")
        return render(request, "expenses/category_form.html", {
            "form": form, "title": f"Edit {category.name}", "category": category,
        })


class CategoryToggleView(PermissionRequiredMixin, View):
    permission_code = "expenses.edit"

    def post(self, request, pk):
        category = get_object_or_404(ExpenseCategory, pk=pk)
        if category.is_system and category.is_active:
            messages.error(
                request,
                "The Salaries category is a system category and cannot be "
                "deactivated.")
            return redirect("expenses:category_list")
        category.is_active = not category.is_active
        category.updated_by = request.user
        category._change_reason = (
            "Deactivated" if not category.is_active else "Reactivated"
        )
        category.save()
        state = "deactivated" if not category.is_active else "reactivated"
        messages.success(request, f"Category '{category.name}' {state}.")
        return redirect("expenses:category_list")


class ExpenseListView(PermissionRequiredMixin, ListView):
    permission_code = "expenses.view"
    model = Expense
    template_name = "expenses/expense_list.html"
    context_object_name = "expenses"
    paginate_by = 25

    def get_queryset(self):
        qs = Expense.objects.select_related("category")
        category_id = parse_int(self.request.GET.get("category", ""))
        if category_id:
            qs = qs.filter(category_id=category_id)
        date_from = parse_date(self.request.GET.get("from", ""))
        date_to = parse_date(self.request.GET.get("to", ""))
        if date_from:
            qs = qs.filter(date__gte=date_from)
        if date_to:
            qs = qs.filter(date__lte=date_to)
        return qs.order_by("-date", "-id")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["categories"] = ExpenseCategory.objects.filter(
            is_active=True).order_by("name")
        context["selected_category"] = self.request.GET.get("category", "")
        context["date_from"] = self.request.GET.get("from", "")
        context["date_to"] = self.request.GET.get("to", "")
        return context


class ExpenseCreateView(PermissionRequiredMixin, View):
    permission_code = "expenses.create"

    def get(self, request):
        return render(request, "expenses/expense_form.html", {
            "form": ExpenseForm(), "title": "Add expense",
        })

    def post(self, request):
        form = ExpenseForm(request.POST)
        if form.is_valid():
            try:
                expense = create_expense(
                    user=request.user,
                    date=form.cleaned_data["date"],
                    category=form.cleaned_data["category"],
                    amount=form.cleaned_data["amount"],
                    description=form.cleaned_data["description"],
                    method=form.cleaned_data["method"],
                )
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                messages.success(request, "Expense added.")
                return redirect("expenses:expense_list")
        return render(request, "expenses/expense_form.html", {
            "form": form, "title": "Add expense",
        })


class ExpenseUpdateView(PermissionRequiredMixin, View):
    permission_code = "expenses.edit"

    def get(self, request, pk):
        expense = get_object_or_404(Expense, pk=pk)
        form = ExpenseForm(instance=expense, require_reason=True)
        return render(request, "expenses/expense_form.html", {
            "form": form, "title": "Edit expense", "expense": expense,
            "read_only": expense.is_payroll_linked,
        })

    def post(self, request, pk):
        expense = get_object_or_404(Expense, pk=pk)
        form = ExpenseForm(request.POST, instance=expense, require_reason=True)
        if form.is_valid():
            try:
                update_expense(
                    expense=expense,
                    user=request.user,
                    date=form.cleaned_data["date"],
                    category=form.cleaned_data["category"],
                    amount=form.cleaned_data["amount"],
                    description=form.cleaned_data["description"],
                    method=form.cleaned_data["method"],
                    reason=form.cleaned_data["reason"],
                    form_version=form.cleaned_data.get("version"),
                )
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                messages.success(request, "Expense updated.")
                return redirect("expenses:expense_list")
        return render(request, "expenses/expense_form.html", {
            "form": form, "title": "Edit expense", "expense": expense,
            "read_only": expense.is_payroll_linked,
        })


class ExpenseDeleteView(PermissionRequiredMixin, View):
    permission_code = "expenses.delete"

    def get(self, request, pk):
        expense = get_object_or_404(Expense, pk=pk)
        return render(request, "expenses/expense_delete.html", {
            "expense": expense, "blocked": expense.is_payroll_linked,
        })

    def post(self, request, pk):
        expense = get_object_or_404(Expense, pk=pk)
        try:
            delete_expense(expense, request.user, request.POST.get("reason", ""))
        except ValidationError as exc:
            messages.error(request, str(exc))
            return redirect("expenses:expense_list")
        messages.success(request, "Expense deleted.")
        return redirect("expenses:expense_list")

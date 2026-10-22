"""The single permission map for the whole system.

Version 1 has exactly one role: ``admin``. Both users are superusers and
hold it. Every view, HTMX endpoint, export and download checks permission
through :func:`has_permission` or :class:`PermissionRequiredMixin` — hiding
a button in the UI is never treated as protection.

Adding a manager role later means adding one map entry here (plus a way to
assign the role to a user); no view code changes.
"""

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse

PERMISSIONS = {
    "admin": frozenset(
        {
            # Sales and invoices
            "sales.create",
            "sales.view",
            "sales.edit",
            "sales.delete",
            # Payments
            "payments.create",
            "payments.view",
            "payments.edit",
            "payments.delete",
            # Customers and products
            "customers.create",
            "customers.view",
            "customers.edit",
            "customers.delete",
            "customers.import",
            "products.manage",
            # Expenses
            "expenses.create",
            "expenses.view",
            "expenses.edit",
            "expenses.delete",
            # Employees and payroll
            "employees.create",
            "employees.view",
            "employees.edit",
            "employees.delete",
            "payroll.view",
            "payroll.generate",
            "payroll.edit",
            "payroll.pay",
            "payroll.reopen",
            # Reports, audit, backups, recycle bin, settings
            "reports.view",
            "reports.export",
            "audit.view",
            "backup.download",
            "backup.create",
            "recycle.view",
            "recycle.restore",
            "settings.edit",
        }
    ),
}


def get_user_role(user):
    """Return the user's role, or None for anonymous / role-less users.

    In Version 1 every real user is a superuser, and superusers are admins.
    """
    if user is None or not user.is_authenticated:
        return None
    if user.is_superuser:
        return "admin"
    return None


def has_permission(user, code):
    """True when the user's role grants this permission code."""
    role = get_user_role(user)
    if role is None:
        return False
    return code in PERMISSIONS.get(role, frozenset())


def permission_required(code):
    """Function-view decorator: login first, then 403 without permission."""

    def decorator(view_func):
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect(f"{reverse('login')}?next={request.path}")
            if not has_permission(request.user, code):
                raise PermissionDenied
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator


class PermissionRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Class-based view mixin. Set ``permission_code`` on the view.

    Anonymous users are redirected to login; authenticated users without
    the permission get 403. (``raise_exception = True`` alone would 403
    anonymous users too, because AccessMixin checks it first.)
    """

    permission_code = None

    def test_func(self):
        if self.permission_code is None:
            return True
        return has_permission(self.request.user, self.permission_code)

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            return redirect(f"{reverse('login')}?next={self.request.path}")
        raise PermissionDenied

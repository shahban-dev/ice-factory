from django.urls import path

from employees import views

app_name = "employees"

urlpatterns = [
    path("", views.EmployeeListView.as_view(), name="list"),
    path("add/", views.EmployeeCreateView.as_view(), name="create"),
    path("<int:pk>/", views.EmployeeDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", views.EmployeeUpdateView.as_view(), name="edit"),
    path("<int:pk>/delete/", views.EmployeeDeleteView.as_view(), name="delete"),
    path("payroll/", views.PayrollListView.as_view(), name="payroll_list"),
    path("payroll/generate/", views.PayrollGenerateView.as_view(), name="payroll_generate"),
    path("payroll/<int:pk>/", views.PayrollDetailView.as_view(), name="payroll_detail"),
    path("payroll/<int:pk>/edit/", views.PayrollUpdateView.as_view(), name="payroll_edit"),
    path("payroll/<int:pk>/pay/", views.PayrollMarkPaidView.as_view(), name="payroll_pay"),
    path("payroll/<int:pk>/reopen/", views.PayrollReopenView.as_view(), name="payroll_reopen"),
    path("payroll/<int:pk>/payslip.pdf", views.PayslipPdfView.as_view(), name="payslip_pdf"),
]

from django.urls import path

from reports import views

app_name = "reports"

urlpatterns = [
    path("", views.ReportsIndexView.as_view(), name="index"),
    path("monthly/", views.MonthlyReportView.as_view(), name="monthly"),
    path("dues/", views.DuesReportView.as_view(), name="dues"),
    path("register/", views.SalesRegisterView.as_view(), name="register"),
    path("expenses/", views.ExpenseReportView.as_view(), name="expense_report"),
    path("audit/", views.AuditLogView.as_view(), name="audit"),
    path("recycle/", views.RecycleBinView.as_view(), name="recycle"),
    path("recycle/restore/", views.RecycleRestoreView.as_view(), name="recycle_restore"),
    path("settings/", views.SettingsView.as_view(), name="settings"),
    path("settings/backup-download/", views.BackupDownloadView.as_view(), name="backup_download"),
]

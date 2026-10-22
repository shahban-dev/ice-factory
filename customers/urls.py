from django.urls import path

from customers import views

app_name = "customers"

urlpatterns = [
    path("", views.CustomerListView.as_view(), name="list"),
    path("add/", views.CustomerCreateView.as_view(), name="create"),
    path("import/", views.CustomerImportUploadView.as_view(), name="import_upload"),
    path("import/preview/", views.CustomerImportPreviewView.as_view(), name="import_preview"),
    path("search-fragment/", views.CustomerSearchFragmentView.as_view(), name="search_fragment"),
    path("<int:pk>/", views.CustomerDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", views.CustomerUpdateView.as_view(), name="edit"),
    path("<int:pk>/delete/", views.CustomerDeleteView.as_view(), name="delete"),
    path("<int:pk>/balance-fragment/", views.CustomerBalanceFragmentView.as_view(), name="balance_fragment"),
    path("<int:pk>/ledger.pdf", views.CustomerLedgerPdfView.as_view(), name="ledger_pdf"),
    path("<int:pk>/ledger.xlsx", views.CustomerLedgerExcelView.as_view(), name="ledger_excel"),
]

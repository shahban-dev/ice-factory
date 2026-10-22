from django.urls import path

from sales import views

app_name = "sales"

urlpatterns = [
    path("products/", views.ProductListView.as_view(), name="product_list"),
    path("products/add/", views.ProductCreateView.as_view(), name="product_create"),
    path("products/<int:pk>/edit/", views.ProductUpdateView.as_view(), name="product_edit"),
    path("products/<int:pk>/toggle/", views.ProductToggleActiveView.as_view(), name="product_toggle"),
    path("", views.SaleListView.as_view(), name="sale_list"),
    path("new/", views.SaleCreateView.as_view(), name="sale_create"),
    path("<int:pk>/", views.SaleDetailView.as_view(), name="sale_detail"),
    path("<int:pk>/edit/", views.SaleUpdateView.as_view(), name="sale_edit"),
    path("<int:pk>/delete/", views.SaleDeleteView.as_view(), name="sale_delete"),
    path("<int:pk>/invoice/", views.InvoiceView.as_view(), name="invoice"),
    path("<int:pk>/invoice.pdf", views.InvoicePdfView.as_view(), name="invoice_pdf"),
    path("payments/", views.PaymentListView.as_view(), name="payment_list"),
    path("payments/new/", views.PaymentCreateView.as_view(), name="payment_create"),
    path("payments/<int:pk>/edit/", views.PaymentUpdateView.as_view(), name="payment_edit"),
    path("payments/<int:pk>/delete/", views.PaymentDeleteView.as_view(), name="payment_delete"),
]

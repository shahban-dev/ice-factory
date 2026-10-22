from django.urls import path

from expenses import views

app_name = "expenses"

urlpatterns = [
    path("categories/", views.CategoryListView.as_view(), name="category_list"),
    path("categories/add/", views.CategoryCreateView.as_view(), name="category_create"),
    path("categories/<int:pk>/edit/", views.CategoryUpdateView.as_view(), name="category_edit"),
    path("categories/<int:pk>/toggle/", views.CategoryToggleView.as_view(), name="category_toggle"),
    path("", views.ExpenseListView.as_view(), name="expense_list"),
    path("add/", views.ExpenseCreateView.as_view(), name="expense_create"),
    path("<int:pk>/edit/", views.ExpenseUpdateView.as_view(), name="expense_edit"),
    path("<int:pk>/delete/", views.ExpenseDeleteView.as_view(), name="expense_delete"),
]

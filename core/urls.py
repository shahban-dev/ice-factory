from django.urls import path

from core import views

urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path("dashboard/activity/", views.DashboardActivityFragment.as_view(), name="dashboard_activity"),
    path("search/", views.GlobalSearchView.as_view(), name="search"),
]

"""Login/logout. Version 1 has no user-management screen: users are
Django superusers created by the developer, and every superuser holds the
single ``admin`` role (see core/permissions.py)."""

from django.contrib.auth import views as auth_views
from django.urls import path

urlpatterns = [
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="registration/login.html"),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
]

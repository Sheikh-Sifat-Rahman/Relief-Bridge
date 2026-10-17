from django.contrib.auth import views as auth
from django.urls import path, reverse_lazy

from . import views
from .forms import PublicLoginForm

app_name = "accounts"
urlpatterns = [
    path("notifications/", views.notifications, name="notifications"),
    path("household/", views.household, name="household"),
    path("register/", views.register, name="register"),
    path(
        "login/",
        auth.LoginView.as_view(
            template_name="registration/login.html", authentication_form=PublicLoginForm
        ),
        name="login",
    ),
    path("logout/", auth.LogoutView.as_view(), name="logout"),
    path("profile/", views.profile, name="profile"),
    path("roles/", views.add_role, name="roles"),
    path(
        "password/",
        auth.PasswordChangeView.as_view(
            template_name="form.html", success_url=reverse_lazy("accounts:profile")
        ),
        name="password",
    ),
]

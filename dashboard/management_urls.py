from django.urls import path

from . import management_views as views

app_name = "management"
urlpatterns = [
    path("", views.home, name="index"),
    path("login/", views.AdminLoginView.as_view(), name="login"),
    path("review/", views.home, name="home"),
    path("profile/", views.profile, name="profile"),
    path("review/<str:kind>/<int:pk>/", views.review, name="review"),
]

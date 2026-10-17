from django.urls import path

from . import views

app_name = "volunteer"
urlpatterns = [
    path("", views.home, name="home"),
    path("profile/", views.home, name="profile"),
    path("assignments/", views.home, name="assignments"),
    path("deliveries/", views.home, name="deliveries"),
    path("warehouse-summary/", views.warehouse, name="warehouse"),
    path("distribution/<int:pk>/", views.detail, name="detail"),
]

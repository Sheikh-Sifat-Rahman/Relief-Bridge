from django.urls import path

from . import views

app_name = "campaigns"
urlpatterns = [
    path("", views.listing, name="list"),
    path("<int:pk>/", views.detail, name="detail"),
]

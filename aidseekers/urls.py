from django.urls import path

from . import views

app_name = "seeker"
urlpatterns = [
    path("", views.home, name="home"),
    path("profile/", views.profile, name="profile"),
    path("request-aid/", views.create, name="create"),
    path("requests/", views.home, name="requests"),
    path("request/<int:pk>/", views.detail, name="detail"),
    path("received-aid/", views.home, name="received"),
    path("distribution-history/", views.home, name="history"),
]

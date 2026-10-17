from django.urls import path

from . import views

app_name = "donor"
urlpatterns = [
    path("item/<int:pk>/photo/", views.photo, name="photo"),
    path("", views.home, name="home"),
    path("profile/", views.profile, name="profile"),
    path("donate-goods/", views.goods, name="goods"),
    path("donate-money/", views.money, name="money"),
    path("donations/", views.home, name="donations"),
    path("history/", views.home, name="history"),
    path("donation/<int:pk>/", views.detail, name="detail"),
]

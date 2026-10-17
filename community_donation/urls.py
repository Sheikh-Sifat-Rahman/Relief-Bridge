from django.contrib import admin
from django.urls import include, path

from accounts.forms import AdminLoginForm
from dashboard import views
from dashboard.management_views import AdminLoginView

urlpatterns = [
    path("", views.public_home, name="home"),
    path("transparency/", views.transparency, name="transparency"),
    path("accounts/", include("accounts.urls")),
    path("dashboard/", include("dashboard.urls")),
    path("campaigns/", include("campaigns.urls")),
    path("donor/", include("donations.urls")),
    path("volunteer/", include("volunteers.urls")),
    path("seeker/", include("aidseekers.urls")),
    path("management/", include("dashboard.management_urls")),
    path("management/operations/login/", AdminLoginView.as_view()),
    path("management/operations/", admin.site.urls),
]
admin.site.site_header = "Community Relief · Management"
admin.site.site_title = "Relief management"

admin.site.login_form = AdminLoginForm

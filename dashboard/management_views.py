from functools import wraps

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from accounts.forms import AdminLoginForm, UserProfileForm
from accounts.models import UserRole
from accounts.permissions import require_staff
from aidseekers.models import AidRequest
from audit.models import AuditLog
from donations.models import Donation

from .reviews import review_aid, review_donation, review_role


def admin_required(view):
    @login_required(login_url="management:login")
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        require_staff(request.user)
        return view(request, *args, **kwargs)

    return wrapped


class AdminLoginView(LoginView):
    template_name = "management/login.html"
    authentication_form = AdminLoginForm

    def get_success_url(self):
        return reverse("management:home")


class ReviewForm(forms.Form):
    decision = forms.ChoiceField(
        choices=[("APPROVE", "Accept"), ("REJECT", "Reject")], widget=forms.RadioSelect
    )
    reason = forms.CharField(
        required=False,
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 3}),
        label="Review notes / rejection reason",
    )

    def clean(self):
        data = super().clean()
        if data.get("decision") == "REJECT" and not data.get("reason", "").strip():
            self.add_error("reason", "A reason is required when rejecting a request.")
        return data


@admin_required
def home(request):
    roles = UserRole.objects.select_related("user", "role").order_by("-created_at")
    donations = Donation.objects.select_related("donor__user", "campaign").order_by(
        "-created_at"
    )
    aid = AidRequest.objects.select_related("seeker__user", "campaign").order_by(
        "-request_date"
    )
    return render(
        request,
        "management/reviews.html",
        {
            "roles": roles.filter(status="PENDING"),
            "donations": donations.filter(review_status="PENDING"),
            "aid_requests": aid.filter(
                status__in=["SUBMITTED", "UNDER_REVIEW", "VERIFIED"]
            ),
            "role_history": roles.exclude(status="PENDING")[:30],
            "donation_history": donations.exclude(review_status="PENDING")[:30],
            "aid_history": aid.exclude(
                status__in=["SUBMITTED", "UNDER_REVIEW", "VERIFIED"]
            )[:30],
            "recent_reviews": AuditLog.objects.filter(
                action__in=[
                    "Role approval",
                    "Role rejection",
                    "Donation acceptance",
                    "Donation rejection",
                    "Aid request approval",
                    "Aid request rejection",
                ]
            ).select_related("user")[:20],
        },
    )


@admin_required
def review(request, kind, pk):
    models = {"role": UserRole, "donation": Donation, "aid": AidRequest}
    services = {"role": review_role, "donation": review_donation, "aid": review_aid}
    if kind not in models:
        from django.http import Http404

        raise Http404
    obj = get_object_or_404(models[kind], pk=pk)
    pending = (
        obj.status == "PENDING"
        if kind == "role"
        else obj.review_status == "PENDING"
        if kind == "donation"
        else obj.status in {"SUBMITTED", "UNDER_REVIEW", "VERIFIED"}
    )
    form = ReviewForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            services[kind](
                request.user,
                obj.pk,
                form.cleaned_data["decision"],
                form.cleaned_data["reason"],
            )
            messages.success(
                request, "Decision saved. The applicant can see the updated status."
            )
            return redirect("management:home")
        except ValidationError as error:
            form.add_error(None, error)
    return render(
        request,
        "management/review_detail.html",
        {"kind": kind, "record": obj, "form": form, "pending": pending},
    )


@admin_required
def profile(request):
    form = UserProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Admin profile updated.")
        return redirect("management:profile")
    return render(request, "management/profile.html", {"form": form})

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .forms import RegistrationForm, UserProfileForm
from .services import request_role


def register(request):
    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            user = form.save()
            for role in form.cleaned_data["roles"]:
                request_role(user, role)
        login(request, user)
        messages.success(
            request,
            "Account created. All roles require admin approval before you can donate or apply for relief.",
        )
        return redirect("dashboard:home")
    return render(request, "form.html", {"form": form, "title": "Join the community"})


@login_required
def profile(request):
    if request.user.is_staff:
        return redirect("management:profile")
    form = UserProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Profile updated.")
        return redirect("accounts:profile")
    return render(
        request,
        "accounts/profile.html",
        {
            "form": form,
            "title": "Your profile",
            "memberships": request.user.user_roles.select_related("role"),
        },
    )


@login_required
@require_POST
def add_role(request):
    name = request.POST.get("role")
    if name in {"DONOR", "VOLUNTEER", "AID_SEEKER"}:
        request_role(request.user, name)
        messages.success(
            request,
            "Role requested. Admin approval is required for every role before donations or relief applications.",
        )
    return redirect("accounts:profile")


@login_required
def household(request):
    from django.core.exceptions import PermissionDenied

    from aidseekers.models import AidSeekerProfile

    from .forms import HouseholdForm

    if not request.user.user_roles.filter(
        role__name="AID_SEEKER", status__in=["PENDING", "ACTIVE"]
    ).exists():
        raise PermissionDenied
    profile, _ = AidSeekerProfile.objects.get_or_create(user=request.user)
    form = HouseholdForm(request.POST or None, instance=profile)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.verification_status = "PENDING"
        obj.save()
        messages.success(request, "Household profile submitted for verification.")
        return redirect("accounts:profile")
    return render(
        request,
        "form.html",
        {"form": form, "title": "Edit household profile", "profile_editor": True},
    )


@login_required
def notifications(request):
    from django.utils import timezone

    from .models import Notification

    entries = Notification.objects.filter(recipient=request.user)
    if request.method == "POST":
        if request.POST.get("notification_id"):
            from django.http import HttpResponseBadRequest

            try:
                notification_id = int(request.POST["notification_id"])
            except (ValueError, TypeError):
                return HttpResponseBadRequest("Invalid notification.")
            entries.filter(pk=notification_id, read_at__isnull=True).update(
                read_at=timezone.now()
            )
        else:
            entries.filter(read_at__isnull=True).update(read_at=timezone.now())
        return redirect("accounts:notifications")
    from django.core.paginator import Paginator

    return render(
        request,
        "accounts/notifications.html",
        {"page": Paginator(entries, 25).get_page(request.GET.get("page"))},
    )

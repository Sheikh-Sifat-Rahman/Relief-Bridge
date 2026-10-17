from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render

from accounts.permissions import active_role_required
from distributions.models import Distribution, DistributionAssignment
from distributions.services import (
    confirm_distribution,
    duplicate_distributions,
    record_duplicate_warning,
)
from inventory.models import InventoryItem


@active_role_required("VOLUNTEER")
def home(request):
    return render(
        request,
        "volunteer/home.html",
        {
            "section": request.resolver_match.url_name,
            "page_title": {
                "assignments": "My assignments",
                "deliveries": "My deliveries",
            }.get(request.resolver_match.url_name, "Volunteer dashboard"),
            "profile": request.user.volunteer_profile,
            "completed_assignments": DistributionAssignment.objects.filter(
                volunteer__user=request.user, status="COMPLETED"
            ).count(),
            "active_assignments": DistributionAssignment.objects.filter(
                volunteer__user=request.user
            )
            .exclude(status="COMPLETED")
            .count(),
            "total_deliveries": Distribution.objects.filter(
                volunteer__user=request.user, status="COMPLETED"
            ).count(),
            "total_items": Distribution.objects.filter(
                volunteer__user=request.user, status="COMPLETED"
            ).aggregate(v=Sum("items__quantity"))["v"]
            or 0,
            "assignments": DistributionAssignment.objects.filter(
                volunteer__user=request.user
            ).select_related("distribution_event"),
            "distributions": Distribution.objects.filter(
                volunteer__user=request.user
            ).select_related("distribution_event"),
        },
    )


@active_role_required("VOLUNTEER")
def warehouse(request):
    warehouse = request.user.volunteer_profile.assigned_warehouse
    items = (
        InventoryItem.objects.filter(warehouse=warehouse)
        if warehouse
        else InventoryItem.objects.none()
    )
    return render(
        request, "volunteer/warehouse.html", {"warehouse": warehouse, "items": items}
    )


@active_role_required("VOLUNTEER")
def detail(request, pk):
    obj = get_object_or_404(
        Distribution.objects.select_related("beneficiary", "distribution_event"),
        pk=pk,
        volunteer__user=request.user,
        distribution_event__distributionassignment__volunteer__user=request.user,
    )
    duplicates = duplicate_distributions(obj)
    if request.method == "POST":
        if duplicates.exists():
            record_duplicate_warning(request.user, obj)
        try:
            confirm_distribution(request.user, obj.pk)
            messages.success(request, "Delivery confirmed and stock ledger updated.")
            return redirect("volunteer:home")
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
    return render(
        request,
        "volunteer/detail.html",
        {"distribution": obj, "duplicates": duplicates},
    )

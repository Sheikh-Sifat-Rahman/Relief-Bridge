from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum
from django.shortcuts import redirect, render

from aidseekers.models import AidRequest
from campaigns.models import DisasterCampaign
from distributions.models import Distribution, DistributionAssignment
from donations.models import Donation, DonationItem, MoneyDonation

from .services import research_statistics


def public_home(request):
    return render(
        request,
        "home.html",
        {
            "campaigns": DisasterCampaign.objects.filter(status="ACTIVE").order_by(
                "-created_at", "-pk"
            )[:3],
            "stats": research_statistics(),
        },
    )


def transparency(request):
    categories = list(
        Distribution.objects.filter(status="COMPLETED")
        .values("items__inventory_item__category")
        .annotate(total=Sum("items__quantity"))
    )
    stats = research_statistics()
    labels = {
        "campaigns": "Active campaigns",
        "donations": "Donations pledged",
        "money": "Simulated donations (BDT)",
        "goods_received": "Goods received",
        "goods_distributed": "Goods delivered",
        "remaining_resources": "Resources available",
        "beneficiaries": "Families assisted",
        "requests": "Aid requests",
        "requests_served": "Requests served",
        "distributions": "Completed deliveries",
        "duplicate_warnings": "Duplicate warnings",
        "duplicate_overrides": "Reviewed overrides",
        "traceability_percent": "Stock ledger reconciliation (%)",
        "average_priority": "Average advisory priority",
        "critical_beneficiaries_served": "Critical households served",
    }
    return render(
        request,
        "transparency.html",
        {
            "stats": stats,
            "metrics": [(label, stats[key]) for key, label in labels.items()],
            "campaigns": DisasterCampaign.objects.filter(status="ACTIVE"),
            "chart_labels": [x["items__inventory_item__category"] for x in categories],
            "chart_values": [float(x["total"] or 0) for x in categories],
        },
    )


@login_required
def home(request):
    if request.user.is_staff:
        return redirect("management:home")
    roles = list(
        request.user.user_roles.filter(status="ACTIVE").values_list(
            "role__name", flat=True
        )
    )
    context = {
        "roles": roles,
        "memberships": request.user.user_roles.select_related("role"),
    }
    if "DONOR" in roles:
        donations = Donation.objects.filter(donor__user=request.user)
        context.update(
            donor=request.user.donor_profile,
            donation_count=donations.count(),
            money_total=MoneyDonation.objects.filter(
                donation__in=donations, payment_status="SUCCESS"
            ).aggregate(v=Sum("amount"))["v"]
            or 0,
            goods_total=DonationItem.objects.filter(donation__in=donations).aggregate(
                v=Sum("quantity")
            )["v"]
            or 0,
            last_donation=donations.order_by("-created_at").first(),
            donation_statuses=donations.values("status").annotate(count=Count("pk")),
        )
    if "VOLUNTEER" in roles:
        deliveries = Distribution.objects.filter(
            volunteer__user=request.user, status="COMPLETED"
        )
        context.update(
            volunteer=request.user.volunteer_profile,
            pending_assignments=DistributionAssignment.objects.filter(
                volunteer__user=request.user
            )
            .exclude(status="COMPLETED")
            .count(),
            completed_deliveries=deliveries.count(),
            delivered_items=deliveries.aggregate(v=Sum("items__quantity"))["v"] or 0,
        )
    if "AID_SEEKER" in roles:
        requests = AidRequest.objects.filter(seeker__user=request.user)
        context.update(
            seeker=request.user.seeker_profile,
            active_requests=requests.exclude(
                status__in=["REJECTED", "COMPLETED"]
            ).count(),
            approved_requests=requests.filter(
                status__in=["APPROVED", "PARTIALLY_APPROVED", "SCHEDULED", "COMPLETED"]
            ).count(),
            rejected_requests=requests.filter(status="REJECTED").count(),
            received_items=Distribution.objects.filter(
                beneficiary__user=request.user, status="COMPLETED"
            ).aggregate(v=Sum("items__quantity"))["v"]
            or 0,
            next_distribution=Distribution.objects.filter(
                beneficiary__user=request.user, status="PLANNED"
            )
            .select_related("distribution_event")
            .order_by("distribution_event__distribution_date")
            .first(),
        )
    return render(request, "dashboard/dashboard.html", context)


def edit_profile(request, form_class, instance):
    form = form_class(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Profile saved.")
        return redirect(request.path)
    return render(
        request,
        "form.html",
        {"form": form, "title": "Edit donor profile", "profile_editor": True},
    )

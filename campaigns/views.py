from django.shortcuts import get_object_or_404, render

from .models import DisasterCampaign


def listing(request):
    return render(
        request,
        "campaigns/list.html",
        {
            "campaigns": DisasterCampaign.objects.filter(status="ACTIVE").order_by(
                "-created_at", "-pk"
            )
        },
    )


def detail(request, pk):
    from django.db.models import Sum

    from distributions.models import Distribution
    from donations.models import DonationItem

    campaign = get_object_or_404(DisasterCampaign, pk=pk, status="ACTIVE")
    return render(
        request,
        "campaigns/detail.html",
        {
            "campaign": campaign,
            "goods": DonationItem.objects.filter(donation__campaign=campaign).aggregate(
                total=Sum("accepted_quantity")
            )["total"]
            or 0,
            "families": Distribution.objects.filter(
                distribution_event__campaign=campaign, status="COMPLETED"
            )
            .values("beneficiary")
            .distinct()
            .count(),
        },
    )

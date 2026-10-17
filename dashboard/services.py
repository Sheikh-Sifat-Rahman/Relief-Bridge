from django.db.models import Avg, Count, Q, Sum

from aidseekers.models import AidRequest
from audit.models import AuditLog
from campaigns.models import DisasterCampaign
from distributions.models import Distribution, DistributionItem
from donations.models import Donation, DonationItem, MoneyDonation
from inventory.models import InventoryItem


def research_statistics():
    completed = Distribution.objects.filter(status="COMPLETED")
    items = InventoryItem.objects.annotate(
        ins=Sum(
            "transactions__quantity",
            filter=Q(transactions__transaction_type="STOCK_IN"),
        ),
        outs=Sum(
            "transactions__quantity",
            filter=Q(transactions__transaction_type="STOCK_OUT"),
        ),
        adjustments=Sum(
            "transactions__quantity",
            filter=Q(transactions__transaction_type="ADJUSTMENT"),
        ),
    )
    traceable = sum(
        (i.ins or 0) - (i.outs or 0) + (i.adjustments or 0) == i.current_quantity
        for i in items
    )
    return {
        "campaigns": DisasterCampaign.objects.filter(status="ACTIVE").count(),
        "donations": Donation.objects.count(),
        "money": MoneyDonation.objects.filter(payment_status="SUCCESS").aggregate(
            v=Sum("amount")
        )["v"]
        or 0,
        "goods_received": DonationItem.objects.aggregate(v=Sum("accepted_quantity"))[
            "v"
        ]
        or 0,
        "goods_distributed": DistributionItem.objects.filter(
            distribution__status="COMPLETED"
        ).aggregate(v=Sum("quantity"))["v"]
        or 0,
        "remaining_resources": InventoryItem.objects.aggregate(
            v=Sum("current_quantity")
        )["v"]
        or 0,
        "beneficiaries": completed.values("beneficiary").distinct().count(),
        "requests": AidRequest.objects.count(),
        "requests_served": completed.values("aid_request").distinct().count(),
        "distributions": completed.count(),
        "duplicate_warnings": AuditLog.objects.filter(
            action="Duplicate warning"
        ).count(),
        "duplicate_overrides": AuditLog.objects.filter(
            action="Duplicate-warning override"
        ).count(),
        "traceability_percent": round(traceable / items.count() * 100, 2)
        if items.count()
        else 100,
        "average_priority": AidRequest.objects.aggregate(v=Avg("priority_score"))["v"]
        or 0,
        "critical_beneficiaries_served": completed.filter(
            aid_request__priority_level="CRITICAL"
        )
        .values("beneficiary")
        .distinct()
        .count(),
        "priority_levels": list(
            AidRequest.objects.values("priority_level").annotate(count=Count("id"))
        ),
    }

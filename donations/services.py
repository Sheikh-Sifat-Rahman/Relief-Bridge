from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from accounts.notifications import notify
from accounts.permissions import has_role, require_staff
from audit.services import generate_code, log
from campaigns.models import DisasterCampaign
from inventory.models import InventoryItem
from inventory.services import move_stock

from .models import Donation, DonationItem, MoneyDonation


@transaction.atomic
def simulate_payment(donor, campaign, amount):
    if not has_role(donor.user, "DONOR"):
        raise PermissionDenied("Admin approval is required before donating.")
    campaign = DisasterCampaign.objects.select_for_update().get(pk=campaign.pk)
    amount = Decimal(str(amount))
    if campaign.status != "ACTIVE" or not amount.is_finite() or amount <= 0:
        raise ValidationError("Invalid donation.")
    donation = Donation.objects.create(
        donor=donor, campaign=campaign, donation_type="MONEY", status="SUBMITTED"
    )
    MoneyDonation.objects.create(
        donation=donation,
        amount=amount,
        transaction_reference=generate_code("SIM"),
        payment_status="PENDING",
    )
    log(
        donor.user,
        "Simulated payment",
        donation,
        "Simulation only; no real payment processed.",
    )
    return donation


@transaction.atomic
def inspect_goods(actor, item_id, warehouse, accepted, reason=""):
    require_staff(actor)
    item = (
        DonationItem.objects.select_for_update()
        .select_related("donation")
        .get(pk=item_id)
    )
    if item.donation.review_status != "APPROVED":
        raise ValidationError(
            "An admin must approve the donation before inspection or stock receipt."
        )
    accepted = Decimal(str(accepted))
    if (
        not accepted.is_finite()
        or item.inspection_status != "PENDING"
        or accepted < 0
        or accepted > item.quantity
    ):
        raise ValidationError("Invalid or repeated inspection.")
    if (
        accepted
        and item.expiration_date
        and item.expiration_date < timezone.localdate()
    ):
        raise ValidationError("Expired goods cannot be received into usable stock.")
    if accepted < item.quantity and not reason.strip():
        raise ValidationError("Give a rejection reason.")
    item.inspected_at = timezone.now()
    item.accepted_quantity = accepted
    item.rejected_quantity = item.quantity - accepted
    item.rejection_reason = reason
    item.inspection_status = (
        "ACCEPTED"
        if accepted == item.quantity
        else "REJECTED"
        if not accepted
        else "PARTIAL"
    )
    item.save()
    if accepted:
        stock, _ = InventoryItem.objects.get_or_create(
            warehouse=warehouse,
            category=item.category,
            item_name=item.item_name,
            unit=item.unit,
        )
        move_stock(
            stock.pk,
            accepted,
            "STOCK_IN",
            actor,
            "DONATION",
            item.donation.donation_code,
            donation_item=item,
        )
    donation = Donation.objects.select_for_update().get(pk=item.donation_id)
    items = donation.items.all()
    if not items.filter(inspection_status="PENDING").exists():
        donation.status = (
            "STORED"
            if all(i.accepted_quantity == i.quantity for i in items)
            else "PARTIALLY_ACCEPTED"
            if any(i.accepted_quantity for i in items)
            else "REJECTED"
        )
        donation.save()
    log(actor, "Donation inspection", item, reason)
    notify(
        donation.donor.user_id,
        f"{donation.donation_code}: inspection completed for {item.item_name}; {accepted} {item.unit} accepted.",
        reverse("donor:detail", args=[donation.pk]),
    )

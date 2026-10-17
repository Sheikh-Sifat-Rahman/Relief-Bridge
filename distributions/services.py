from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from accounts.notifications import notify
from accounts.permissions import has_role, require_staff
from aidseekers.models import AidSeekerProfile
from audit.services import log
from inventory.models import InventoryBatch, InventoryItem
from inventory.services import move_stock, usable_batches

from .models import Distribution, DistributionAllocation, DistributionAssignment


def duplicate_distributions(distribution):
    categories = distribution.items.values_list("inventory_item__category", flat=True)
    return (
        Distribution.objects.filter(
            beneficiary=distribution.beneficiary,
            distribution_event__campaign=distribution.distribution_event.campaign,
            status="COMPLETED",
            items__inventory_item__category__in=categories,
        )
        .exclude(pk=distribution.pk)
        .distinct()
    )


def record_duplicate_warning(actor, distribution):
    if not distribution.duplicate_warning:
        distribution.duplicate_warning = True
        distribution.save(update_fields=["duplicate_warning"])
        log(actor, "Duplicate warning", distribution)


@transaction.atomic
def confirm_distribution(actor, distribution_id, override_reason=""):
    distribution = (
        Distribution.objects.select_for_update()
        .select_related("distribution_event", "aid_request", "volunteer__user")
        .get(pk=distribution_id)
    )
    event = distribution.distribution_event
    assigned = (
        has_role(actor, "VOLUNTEER")
        and distribution.volunteer.user_id == actor.pk
        and DistributionAssignment.objects.filter(
            distribution_event=event,
            volunteer=distribution.volunteer,
            status__in=["ASSIGNED", "ACCEPTED", "IN_PROGRESS"],
        ).exists()
    )
    if not actor.is_active or not (actor.is_staff or assigned):
        raise PermissionDenied
    if distribution.status != "PLANNED":
        raise ValidationError("Distribution is already completed or cancelled.")
    if event.status not in {"PLANNED", "ACTIVE"}:
        raise ValidationError("Event is not available for distribution.")
    if (
        distribution.aid_request.seeker_id != distribution.beneficiary_id
        or distribution.aid_request.campaign_id != event.campaign_id
    ):
        raise ValidationError("Beneficiary or campaign mismatch.")
    if distribution.aid_request.status not in {
        "APPROVED",
        "PARTIALLY_APPROVED",
        "SCHEDULED",
        "COMPLETED",
    }:
        raise ValidationError("A coordinator must approve the aid request first.")
    AidSeekerProfile.objects.select_for_update().get(pk=distribution.beneficiary_id)
    items = list(
        distribution.items.select_related("inventory_item").order_by(
            "inventory_item_id"
        )
    )
    if not items:
        raise ValidationError("Add distribution items first.")
    duplicates = duplicate_distributions(distribution)
    if duplicates.exists() and not (actor.is_staff and override_reason.strip()):
        raise ValidationError(
            "Possible duplicate aid detected. A coordinator must review the previous distributions and provide an override reason."
        )
    if duplicates.exists():
        record_duplicate_warning(actor, distribution)
        distribution.override_reason = override_reason.strip()
        log(actor, "Duplicate-warning override", distribution, override_reason)
    _reserve(distribution)
    for item in items:
        if (
            item.inventory_item.warehouse_id != event.warehouse_id
            or item.unit != item.inventory_item.unit
        ):
            raise ValidationError("Warehouse or unit mismatch.")
        allocations = list(
            item.allocations.select_for_update()
            .filter(status="RESERVED")
            .order_by("batch_id")
        )
        if sum(a.quantity for a in allocations) != item.quantity:
            raise ValidationError("Reservation no longer matches delivery items.")
        for allocation in allocations:
            batch = InventoryBatch.objects.select_for_update().get(
                pk=allocation.batch_id
            )
            if batch.expiration_date and batch.expiration_date < timezone.localdate():
                raise ValidationError(
                    "Reserved goods have expired. Cancel this delivery and schedule fresh stock."
                )
            batch.remaining_quantity -= allocation.quantity
            batch.reserved_quantity -= allocation.quantity
            batch.save(update_fields=["remaining_quantity", "reserved_quantity"])
            allocation.status = "DELIVERED"
            allocation.save(update_fields=["status", "updated_at"])
        move_stock(
            item.inventory_item_id,
            item.quantity,
            "STOCK_OUT",
            actor,
            "DISTRIBUTION",
            distribution.distribution_code,
            _distribution=True,
            _allocated=True,
        )
    distribution.status = "COMPLETED"
    distribution.distributed_at = timezone.now()
    distribution.save()
    distribution.aid_request.status = "COMPLETED"
    distribution.aid_request.save()
    log(actor, "Distribution completion", distribution)
    notify(
        distribution.beneficiary.user_id,
        f"Delivery {distribution.distribution_code} has been completed.",
        reverse("seeker:home"),
    )
    _notify_donors(distribution, "delivered")
    return distribution


def _reserve(distribution):
    """Caller holds the distribution lock; stock locks serialize all allocations."""
    if (
        distribution.status != "PLANNED"
        or distribution.distribution_event.status not in {"PLANNED", "ACTIVE"}
    ):
        raise ValidationError("Only planned deliveries in open events can be reserved.")
    if distribution.aid_request.status not in {
        "APPROVED",
        "PARTIALLY_APPROVED",
        "SCHEDULED",
        "COMPLETED",
    }:
        raise ValidationError("Approve the relief request before scheduling delivery.")
    if (
        distribution.aid_request.seeker_id != distribution.beneficiary_id
        or distribution.aid_request.campaign_id
        != distribution.distribution_event.campaign_id
    ):
        raise ValidationError("Request, beneficiary and campaign must match.")
    if not DistributionAssignment.objects.filter(
        distribution_event=distribution.distribution_event,
        volunteer=distribution.volunteer,
        status__in=["ASSIGNED", "ACCEPTED", "IN_PROGRESS"],
    ).exists():
        raise ValidationError("Assign an active volunteer to this event first.")
    lines = list(distribution.items.order_by("inventory_item_id"))
    if not lines:
        raise ValidationError("Add distribution items first.")
    for line in lines:
        stock = InventoryItem.objects.select_for_update().get(pk=line.inventory_item_id)
        if (
            stock.warehouse_id != distribution.distribution_event.warehouse_id
            or line.unit != stock.unit
        ):
            raise ValidationError("Warehouse or unit mismatch.")
        existing = list(line.allocations.filter(status="RESERVED"))
        if existing:
            if sum(a.quantity for a in existing) != line.quantity:
                raise ValidationError(
                    "Cancel the reservation before changing delivery quantities."
                )
            continue
        needed = line.quantity
        for batch in usable_batches(
            stock,
            max(
                timezone.localdate(),
                timezone.localdate(distribution.distribution_event.distribution_date),
            ),
        ):
            taken = min(needed, batch.remaining_quantity - batch.reserved_quantity)
            DistributionAllocation.objects.create(
                distribution_item=line, batch=batch, quantity=taken
            )
            batch.reserved_quantity += taken
            batch.save(update_fields=["reserved_quantity"])
            needed -= taken
            if not needed:
                break
        if needed:
            raise ValidationError(
                f"Not enough usable, unreserved stock for {stock.item_name}."
            )


def _notify_donors(distribution, action):
    ids = (
        DistributionAllocation.objects.filter(
            distribution_item__distribution=distribution,
            batch__donation_item__isnull=False,
        )
        .values_list("batch__donation_item__donation_id", flat=True)
        .distinct()
    )
    from donations.models import Donation

    for donation in Donation.objects.filter(pk__in=ids).select_related("donor"):
        notify(
            donation.donor.user_id,
            f"Goods from {donation.donation_code}: delivery {action}. View your donation for quantities.",
            reverse("donor:detail", args=[donation.pk]),
        )


@transaction.atomic
def reserve_distribution(actor, distribution_id):
    require_staff(actor)
    distribution = Distribution.objects.select_for_update().get(pk=distribution_id)
    if DistributionAllocation.objects.filter(
        distribution_item__distribution=distribution, status="RESERVED"
    ).exists():
        raise ValidationError("This delivery already has a stock reservation.")
    _reserve(distribution)
    log(actor, "Stock reserved", distribution)
    notify(
        distribution.volunteer.user_id,
        f"Delivery {distribution.distribution_code} is scheduled; stock is reserved.",
        reverse("volunteer:detail", args=[distribution.pk]),
    )
    notify(
        distribution.beneficiary.user_id,
        f"Your delivery {distribution.distribution_code} is scheduled.",
        reverse("seeker:home"),
    )
    _notify_donors(distribution, "scheduled")
    return distribution


@transaction.atomic
def cancel_distribution(actor, distribution_id):
    require_staff(actor)
    distribution = Distribution.objects.select_for_update().get(pk=distribution_id)
    if distribution.status != "PLANNED":
        raise ValidationError("Only planned deliveries can be cancelled.")
    allocations = list(
        DistributionAllocation.objects.filter(
            distribution_item__distribution=distribution, status="RESERVED"
        ).order_by("batch__inventory_item_id", "batch_id")
    )
    for allocation in allocations:
        InventoryItem.objects.select_for_update().get(
            pk=allocation.batch.inventory_item_id
        )
        batch = InventoryBatch.objects.select_for_update().get(pk=allocation.batch_id)
        batch.reserved_quantity -= allocation.quantity
        batch.save(update_fields=["reserved_quantity"])
        allocation.status = "RELEASED"
        allocation.save(update_fields=["status", "updated_at"])
    distribution.status = "CANCELLED"
    distribution.save(update_fields=["status"])
    log(actor, "Distribution cancelled; stock released", distribution)
    notify(
        distribution.volunteer.user_id,
        f"Delivery {distribution.distribution_code} was cancelled.",
        reverse("volunteer:home"),
    )
    notify(
        distribution.beneficiary.user_id,
        f"Delivery {distribution.distribution_code} was cancelled. Your relief request remains on record.",
        reverse("seeker:home"),
    )
    _notify_donors(distribution, "cancelled; reservation released")
    return distribution

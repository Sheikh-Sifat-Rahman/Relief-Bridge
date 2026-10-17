from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.permissions import has_role
from aidseekers.models import AidSeekerProfile
from audit.services import log
from inventory.services import move_stock

from .models import Distribution, DistributionAssignment


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
    for item in items:
        if (
            item.inventory_item.warehouse_id != event.warehouse_id
            or item.unit != item.inventory_item.unit
        ):
            raise ValidationError("Warehouse or unit mismatch.")
        move_stock(
            item.inventory_item_id,
            item.quantity,
            "STOCK_OUT",
            actor,
            "DISTRIBUTION",
            distribution.distribution_code,
            _distribution=True,
        )
    distribution.status = "COMPLETED"
    distribution.distributed_at = timezone.now()
    distribution.save()
    distribution.aid_request.status = "COMPLETED"
    distribution.aid_request.save()
    log(actor, "Distribution completion", distribution)
    return distribution

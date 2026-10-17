from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from accounts.permissions import require_staff
from audit.services import log

from .models import InventoryBatch, InventoryItem, InventoryTransaction


@transaction.atomic
def move_stock(
    item_id,
    quantity,
    transaction_type,
    actor,
    source_type,
    source_reference,
    notes="",
    *,
    _distribution=False,
    donation_item=None,
    _allocated=False,
):
    if not _distribution:
        require_staff(actor)
    quantity = Decimal(str(quantity))
    if (
        not quantity.is_finite()
        or not quantity
        or transaction_type not in {"STOCK_IN", "STOCK_OUT", "ADJUSTMENT"}
    ):
        raise ValidationError("Invalid stock movement.")
    if transaction_type != "ADJUSTMENT" and quantity <= 0:
        raise ValidationError("Quantity must be positive.")
    item = InventoryItem.objects.select_for_update().get(pk=item_id)
    delta = -quantity if transaction_type == "STOCK_OUT" else quantity
    if item.current_quantity + delta < 0:
        raise ValidationError("Insufficient inventory.")
    if not _allocated:
        if delta > 0:
            InventoryBatch.objects.create(
                inventory_item=item,
                donation_item=donation_item,
                source="DONATION" if donation_item else "MANUAL",
                received_quantity=delta,
                remaining_quantity=delta,
                expiration_date=donation_item.expiration_date
                if donation_item
                else None,
            )
        else:
            needed = -delta
            # Manual corrections may remove expired stock, but never reserved stock.
            batches = item.batches.select_for_update().order_by(
                F("expiration_date").asc(nulls_last=True), "received_at", "pk"
            )
            for batch in batches:
                taken = min(needed, batch.remaining_quantity - batch.reserved_quantity)
                if taken:
                    batch.remaining_quantity -= taken
                    batch.save(update_fields=["remaining_quantity"])
                    needed -= taken
                if not needed:
                    break
            if needed:
                raise ValidationError(
                    "Insufficient unreserved stock. Cancel reservations before removing stock."
                )
    movement = InventoryTransaction.objects.create(
        inventory_item=item,
        quantity=quantity,
        transaction_type=transaction_type,
        performed_by=actor,
        source_type=source_type,
        source_reference=source_reference,
        notes=notes,
    )
    item.current_quantity += delta
    item.save(update_fields=["current_quantity", "updated_at"])
    log(actor, transaction_type, movement, notes)
    return movement


def usable_batches(item, on_date=None):
    return (
        item.batches.select_for_update()
        .filter(
            Q(expiration_date__isnull=True)
            | Q(expiration_date__gte=on_date or timezone.localdate()),
            remaining_quantity__gt=F("reserved_quantity"),
        )
        .order_by(F("expiration_date").asc(nulls_last=True), "received_at", "pk")
    )

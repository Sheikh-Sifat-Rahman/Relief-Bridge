from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from accounts.permissions import require_staff
from audit.services import log

from .models import InventoryItem, InventoryTransaction


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

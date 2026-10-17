from django.conf import settings
from django.db import models

CATEGORIES = [
    (x, x.replace("_", " ").title())
    for x in [
        "CLOTHING",
        "DRY_FOOD",
        "WATER",
        "BLANKET",
        "HYGIENE",
        "HOUSEHOLD",
        "EDUCATION",
        "OTHER",
    ]
]


class Warehouse(models.Model):
    name = models.CharField(max_length=120)
    district = models.CharField(max_length=80)
    upazila = models.CharField(max_length=80, blank=True)
    address = models.TextField()
    status = models.CharField(
        max_length=12,
        default="ACTIVE",
        choices=[("ACTIVE", "Active"), ("INACTIVE", "Inactive")],
    )

    def __str__(self):
        return self.name


class InventoryItem(models.Model):
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    category = models.CharField(max_length=20, choices=CATEGORIES)
    item_name = models.CharField(max_length=120)
    unit = models.CharField(max_length=30)
    current_quantity = models.DecimalField(
        max_digits=14, decimal_places=2, default=0, editable=False
    )
    minimum_stock_level = models.DecimalField(
        max_digits=14, decimal_places=2, default=0
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(current_quantity__gte=0), name="nonnegative_stock"
            ),
            models.UniqueConstraint(
                fields=["warehouse", "category", "item_name", "unit"],
                name="unique_warehouse_item",
            ),
        ]

    def __str__(self):
        return f"{self.item_name} ({self.warehouse})"


class InventoryTransaction(models.Model):
    inventory_item = models.ForeignKey(
        InventoryItem, on_delete=models.PROTECT, related_name="transactions"
    )
    transaction_type = models.CharField(
        max_length=12, choices=[(x, x) for x in ["STOCK_IN", "STOCK_OUT", "ADJUSTMENT"]]
    )
    quantity = models.DecimalField(max_digits=14, decimal_places=2)
    source_type = models.CharField(max_length=40)
    source_reference = models.CharField(max_length=100)
    performed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(transaction_type="ADJUSTMENT") & ~models.Q(quantity=0)
                )
                | models.Q(
                    transaction_type__in=["STOCK_IN", "STOCK_OUT"], quantity__gt=0
                ),
                name="valid_movement_sign",
            )
        ]

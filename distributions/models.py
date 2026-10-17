from django.conf import settings
from django.db import models


class DistributionEvent(models.Model):
    campaign = models.ForeignKey("campaigns.DisasterCampaign", on_delete=models.PROTECT)
    warehouse = models.ForeignKey("inventory.Warehouse", on_delete=models.PROTECT)
    name = models.CharField(max_length=120)
    location = models.CharField(max_length=180)
    distribution_date = models.DateTimeField()
    status = models.CharField(
        max_length=12,
        default="PLANNED",
        choices=[(x, x) for x in ["PLANNED", "ACTIVE", "COMPLETED", "CANCELLED"]],
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class DistributionAssignment(models.Model):
    distribution_event = models.ForeignKey(DistributionEvent, on_delete=models.PROTECT)
    volunteer = models.ForeignKey(
        "volunteers.VolunteerProfile", on_delete=models.PROTECT
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=12,
        default="ASSIGNED",
        choices=[(x, x) for x in ["ASSIGNED", "ACCEPTED", "IN_PROGRESS", "COMPLETED"]],
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["distribution_event", "volunteer"],
                name="unique_event_volunteer",
            )
        ]


class Distribution(models.Model):
    distribution_code = models.CharField(max_length=40, unique=True, editable=False)
    distribution_event = models.ForeignKey(DistributionEvent, on_delete=models.PROTECT)
    aid_request = models.ForeignKey("aidseekers.AidRequest", on_delete=models.PROTECT)
    beneficiary = models.ForeignKey(
        "aidseekers.AidSeekerProfile", on_delete=models.PROTECT
    )
    volunteer = models.ForeignKey(
        "volunteers.VolunteerProfile", on_delete=models.PROTECT
    )
    distributed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=12,
        default="PLANNED",
        choices=[
            ("PLANNED", "Planned"),
            ("COMPLETED", "Completed"),
            ("CANCELLED", "Cancelled"),
        ],
    )
    notes = models.TextField(blank=True)
    duplicate_warning = models.BooleanField(default=False, editable=False)
    override_reason = models.TextField(blank=True, editable=False)

    def save(self, *args, **kwargs):
        from audit.services import generate_code

        if not self.distribution_code:
            self.distribution_code = generate_code("DIST")
        super().save(*args, **kwargs)

    def __str__(self):
        return self.distribution_code


class DistributionItem(models.Model):
    distribution = models.ForeignKey(
        Distribution, on_delete=models.PROTECT, related_name="items"
    )
    inventory_item = models.ForeignKey(
        "inventory.InventoryItem", on_delete=models.PROTECT
    )
    quantity = models.DecimalField(max_digits=14, decimal_places=2)
    unit = models.CharField(max_length=30)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name="positive_distribution_quantity",
            ),
            models.UniqueConstraint(
                fields=["distribution", "inventory_item"],
                name="unique_distribution_stock",
            ),
        ]

from django.conf import settings
from django.db import models


class VolunteerProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="volunteer_profile",
    )
    assigned_area = models.CharField(max_length=120, blank=True)
    assigned_warehouse = models.ForeignKey(
        "inventory.Warehouse", on_delete=models.PROTECT, null=True, blank=True
    )
    volunteer_status = models.CharField(
        max_length=12,
        default="PENDING",
        choices=[(x, x) for x in ["PENDING", "ACTIVE", "INACTIVE", "SUSPENDED"]],
    )
    joined_at = models.DateTimeField(auto_now_add=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="approved_volunteers",
        null=True,
        blank=True,
    )
    notes = models.TextField(blank=True)

    def __str__(self):
        return self.user.username

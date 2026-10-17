from django.conf import settings
from django.db import models


class DisasterCampaign(models.Model):
    name = models.CharField(max_length=180)
    disaster_type = models.CharField(
        max_length=20,
        choices=[
            (x, x.title())
            for x in [
                "FLOOD",
                "CYCLONE",
                "STORM",
                "RIVER_EROSION",
                "LANDSLIDE",
                "FIRE",
                "OTHER",
            ]
        ],
    )
    description = models.TextField()
    district = models.CharField(max_length=80)
    upazila = models.CharField(max_length=80, blank=True)
    union_name = models.CharField(max_length=80, blank=True)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    target_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    collected_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=0, editable=False
    )
    status = models.CharField(
        max_length=12,
        default="DRAFT",
        choices=[(x, x) for x in ["DRAFT", "ACTIVE", "PAUSED", "COMPLETED", "CLOSED"]],
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def progress(self):
        return (
            min(100, round(self.collected_amount / self.target_amount * 100))
            if self.target_amount
            else 0
        )

    def __str__(self):
        return self.name

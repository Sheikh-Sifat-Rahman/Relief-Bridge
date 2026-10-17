from django.conf import settings
from django.db import models

DAMAGE = [(x, x.title()) for x in ["NONE", "PARTIAL", "SEVERE", "DESTROYED"]]
VERIFY = [(x, x.title()) for x in ["PENDING", "VERIFIED", "REJECTED"]]


class Vulnerability(models.Model):
    family_members = models.PositiveIntegerField(default=1)
    children_count = models.PositiveIntegerField(default=0)
    elderly_count = models.PositiveIntegerField(default=0)
    displaced = models.BooleanField(default=False)
    income_lost = models.BooleanField(default=False)
    house_damage = models.CharField(max_length=12, choices=DAMAGE, default="NONE")
    safe_water_available = models.BooleanField(default=True)

    class Meta:
        abstract = True
        constraints = [
            models.CheckConstraint(
                condition=models.Q(family_members__gte=1)
                & models.Q(
                    family_members__gte=models.F("children_count")
                    + models.F("elderly_count")
                ),
                name="%(app_label)s_%(class)s_valid_family",
            )
        ]

    def clean(self):
        from django.core.exceptions import ValidationError

        if (
            self.family_members < 1
            or self.children_count + self.elderly_count > self.family_members
        ):
            raise ValidationError(
                "Family size must include all children and elderly members."
            )


class AidSeekerProfile(Vulnerability):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="seeker_profile",
    )
    full_name = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    district = models.CharField(max_length=80, blank=True)
    upazila = models.CharField(max_length=80, blank=True)
    union_name = models.CharField(max_length=80, blank=True)
    village_or_area = models.CharField(max_length=120, blank=True)
    verification_status = models.CharField(
        max_length=12, choices=VERIFY, default="PENDING"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.full_name or self.user.username


class AidRequest(Vulnerability):
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reviewed_aid_requests",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_reason = models.TextField(blank=True)
    request_code = models.CharField(max_length=40, unique=True, editable=False)
    seeker = models.ForeignKey(
        AidSeekerProfile, on_delete=models.PROTECT, related_name="requests"
    )
    campaign = models.ForeignKey("campaigns.DisasterCampaign", on_delete=models.PROTECT)
    request_date = models.DateTimeField(auto_now_add=True)
    requested_items = models.TextField()
    explanation = models.TextField()
    verification_status = models.CharField(
        max_length=12, choices=VERIFY, default="PENDING"
    )
    priority_score = models.PositiveSmallIntegerField(default=0, editable=False)
    priority_level = models.CharField(max_length=12, default="LOW", editable=False)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=24,
        default="SUBMITTED",
        choices=[
            (x, x)
            for x in [
                "SUBMITTED",
                "UNDER_REVIEW",
                "VERIFIED",
                "APPROVED",
                "PARTIALLY_APPROVED",
                "REJECTED",
                "SCHEDULED",
                "COMPLETED",
            ]
        ],
    )

    def save(self, *args, **kwargs):
        from audit.services import generate_code

        from .services import calculate_priority_score

        if not self.request_code:
            self.request_code = generate_code("REQ")
        self.priority_score, self.priority_level = calculate_priority_score(self)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.request_code

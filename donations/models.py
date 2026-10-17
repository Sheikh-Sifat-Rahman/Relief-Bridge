from django.db import models

from inventory.models import CATEGORIES

from .uploads import goods_photo_path


class Donation(models.Model):
    review_status = models.CharField(
        max_length=12,
        default="PENDING",
        choices=[
            ("PENDING", "Pending"),
            ("APPROVED", "Approved"),
            ("REJECTED", "Rejected"),
        ],
    )
    reviewed_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reviewed_donations",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_reason = models.TextField(blank=True)
    donation_code = models.CharField(max_length=40, unique=True, editable=False)
    donor = models.ForeignKey(
        "accounts.DonorProfile", on_delete=models.PROTECT, related_name="donations"
    )
    campaign = models.ForeignKey("campaigns.DisasterCampaign", on_delete=models.PROTECT)
    donation_type = models.CharField(
        max_length=8, choices=[("GOODS", "Goods"), ("MONEY", "Money")]
    )
    status = models.CharField(
        max_length=24,
        default="SUBMITTED",
        choices=[
            (x, x)
            for x in [
                "SUBMITTED",
                "COLLECTION_SCHEDULED",
                "RECEIVED",
                "INSPECTED",
                "ACCEPTED",
                "PARTIALLY_ACCEPTED",
                "REJECTED",
                "STORED",
                "ALLOCATED",
                "DISTRIBUTED",
            ]
        ],
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        from audit.services import generate_code

        if not self.donation_code:
            self.donation_code = generate_code("DON")
        super().save(*args, **kwargs)

    def __str__(self):
        return self.donation_code


class DonationItem(models.Model):
    photo = models.ImageField(
        upload_to=goods_photo_path,
        blank=True,
        help_text="Optional. JPEG, PNG or WebP; up to 5 MB.",
    )
    donation = models.ForeignKey(
        Donation, on_delete=models.PROTECT, related_name="items"
    )
    category = models.CharField(max_length=20, choices=CATEGORIES)
    item_name = models.CharField(max_length=120)
    quantity = models.DecimalField(max_digits=14, decimal_places=2)
    unit = models.CharField(max_length=30)
    condition = models.CharField(max_length=120)
    expiration_date = models.DateField(null=True, blank=True)
    inspection_status = models.CharField(
        max_length=12,
        default="PENDING",
        choices=[(x, x) for x in ["PENDING", "ACCEPTED", "PARTIAL", "REJECTED"]],
    )
    accepted_quantity = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    rejected_quantity = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    rejection_reason = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0), name="positive_donation_quantity"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    accepted_quantity__gte=0,
                    rejected_quantity__gte=0,
                    quantity__gte=models.F("accepted_quantity")
                    + models.F("rejected_quantity"),
                ),
                name="valid_inspection_quantities",
            ),
        ]


class MoneyDonation(models.Model):
    donation = models.OneToOneField(
        Donation, on_delete=models.PROTECT, related_name="payment"
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    payment_method = models.CharField(
        max_length=30, default="SIMULATION", editable=False
    )
    transaction_reference = models.CharField(max_length=40, unique=True, editable=False)
    payment_status = models.CharField(
        max_length=10,
        default="PENDING",
        choices=[(x, x) for x in ["PENDING", "SUCCESS", "FAILED"]],
    )
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0), name="positive_money_donation"
            )
        ]

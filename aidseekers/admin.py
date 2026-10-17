from django.contrib import admin
from django.utils import timezone

from audit.services import log

from .models import AidRequest, AidSeekerProfile


@admin.register(AidSeekerProfile)
class SeekerAdmin(admin.ModelAdmin):
    list_display = ["user", "full_name", "district", "verification_status"]

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        log(request.user, "Beneficiary verification", obj, obj.verification_status)


@admin.register(AidRequest)
class AidRequestAdmin(admin.ModelAdmin):
    list_display = [
        "request_code",
        "campaign",
        "status",
        "verification_status",
        "priority_score",
        "priority_level",
    ]
    list_filter = ["status", "verification_status", "priority_level"]
    readonly_fields = [
        "request_code",
        "request_date",
        "priority_score",
        "priority_level",
        "verified_by",
        "verified_at",
        "status",
        "reviewed_by",
        "reviewed_at",
        "review_reason",
    ]

    def save_model(self, request, obj, form, change):
        if obj.verification_status == "VERIFIED":
            obj.verified_by = request.user
            obj.verified_at = timezone.now()
        super().save_model(request, obj, form, change)
        log(
            request.user,
            "Aid request approval"
            if obj.status in {"APPROVED", "PARTIALLY_APPROVED"}
            else "Aid request review",
            obj,
            obj.status,
        )

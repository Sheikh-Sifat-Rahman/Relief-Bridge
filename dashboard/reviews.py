from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from accounts.models import UserRole
from accounts.permissions import require_staff
from accounts.services import approve_role
from aidseekers.models import AidRequest
from audit.services import log
from campaigns.models import DisasterCampaign
from donations.models import Donation, MoneyDonation


def validate_decision(decision, reason):
    if decision not in {"APPROVE", "REJECT"}:
        raise ValidationError("Choose Accept or Reject.")
    if decision == "REJECT" and not reason.strip():
        raise ValidationError("Explain why this request is being rejected.")


@transaction.atomic
def review_role(actor, pk, decision, reason=""):
    require_staff(actor)
    validate_decision(decision, reason)
    membership = (
        UserRole.objects.select_for_update().select_related("role", "user").get(pk=pk)
    )
    if membership.status != "PENDING":
        raise ValidationError("This access request has already been reviewed.")
    membership.review_reason = reason.strip()
    if decision == "APPROVE":
        approve_role(actor, membership)
    else:
        membership.status = "REJECTED"
        membership.approved_at = None
        membership.save()
        log(actor, "Role rejection", membership, reason)
    return membership


@transaction.atomic
def review_donation(actor, pk, decision, reason=""):
    require_staff(actor)
    validate_decision(decision, reason)
    donation = Donation.objects.select_for_update().get(pk=pk)
    if donation.review_status != "PENDING":
        raise ValidationError("This donation has already been reviewed.")
    donation.review_status = "APPROVED" if decision == "APPROVE" else "REJECTED"
    donation.status = "ACCEPTED" if decision == "APPROVE" else "REJECTED"
    donation.reviewed_by = actor
    donation.reviewed_at = timezone.now()
    donation.review_reason = reason.strip()
    if donation.donation_type == "MONEY":
        payment = MoneyDonation.objects.select_for_update().get(donation=donation)
        payment.payment_status = "SUCCESS" if decision == "APPROVE" else "FAILED"
        payment.paid_at = timezone.now() if decision == "APPROVE" else None
        payment.save()
        if decision == "APPROVE":
            campaign = DisasterCampaign.objects.select_for_update().get(
                pk=donation.campaign_id
            )
            campaign.collected_amount = F("collected_amount") + payment.amount
            campaign.save(update_fields=["collected_amount", "updated_at"])
    donation.save()
    log(
        actor,
        "Donation acceptance" if decision == "APPROVE" else "Donation rejection",
        donation,
        reason,
    )
    return donation


@transaction.atomic
def review_aid(actor, pk, decision, reason=""):
    require_staff(actor)
    validate_decision(decision, reason)
    aid = AidRequest.objects.select_for_update().get(pk=pk)
    if aid.status not in {"SUBMITTED", "UNDER_REVIEW", "VERIFIED"}:
        raise ValidationError("This relief application has already been reviewed.")
    aid.status = "APPROVED" if decision == "APPROVE" else "REJECTED"
    aid.verification_status = "VERIFIED" if decision == "APPROVE" else "REJECTED"
    aid.verified_by = actor
    aid.verified_at = timezone.now()
    aid.reviewed_by = actor
    aid.reviewed_at = timezone.now()
    aid.review_reason = reason.strip()
    aid.save()
    log(
        actor,
        "Aid request approval" if decision == "APPROVE" else "Aid request rejection",
        aid,
        reason,
    )
    return aid

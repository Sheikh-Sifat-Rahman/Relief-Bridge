"""Notify affected users when saved workflow records change.

Signals cover both service actions and Operations edits. QuerySet.update bypasses
signals: workflow changes should use save() or an explicit notification service.
"""

from django.db.models.signals import post_delete, post_save, pre_save
from django.urls import reverse

from aidseekers.models import AidRequest, AidSeekerProfile
from distributions.models import Distribution, DistributionAssignment, DistributionEvent
from donations.models import Donation, DonationItem
from volunteers.models import VolunteerProfile

from .models import UserRole
from .notifications import notify, notify_staff

TRACKED = {
    UserRole: ("status", "review_reason"),
    Donation: ("review_status", "status", "review_reason"),
    DonationItem: ("inspection_status",),
    AidRequest: ("status", "verification_status", "review_reason"),
    AidSeekerProfile: ("verification_status",),
    VolunteerProfile: ("volunteer_status", "assigned_area", "assigned_warehouse_id"),
    DistributionAssignment: ("status", "volunteer_id", "distribution_event_id"),
    DistributionEvent: ("status", "location", "distribution_date", "name"),
    Distribution: ("status", "volunteer_id", "beneficiary_id", "distribution_event_id"),
}


def remember_state(sender, instance, raw=False, using="default", **kwargs):
    if raw:
        return
    instance._notification_before = (
        sender.objects.using(using)
        .filter(pk=instance.pk)
        .values(*TRACKED[sender])
        .first()
        if instance.pk
        else None
    )


def workflow_saved(sender, instance, created, raw=False, using="default", **kwargs):
    if raw:
        return
    before = getattr(instance, "_notification_before", None)
    obj = sender.objects.using(using).get(pk=instance.pk)
    changed = {
        field
        for field in TRACKED[sender]
        if before is not None and before[field] != getattr(obj, field)
    }
    if not created and not changed:
        return

    def send(user_id, message, link):
        notify(user_id, message, link, using=using)

    def staff(message, link):
        notify_staff(message, link, using=using)

    if sender is UserRole:
        role = obj.role.get_name_display()
        send(
            obj.user_id,
            f"Your {role} access request: {obj.get_status_display()}. {obj.review_reason}",
            reverse("accounts:profile"),
        )
        if obj.status == "PENDING":
            staff(
                f"New {role} access request awaiting review.",
                reverse("management:review", args=["role", obj.pk]),
            )
    elif sender is Donation:
        link = reverse("donor:detail", args=[obj.pk])
        if created:
            send(
                obj.donor.user_id,
                f"Donation {obj.donation_code} submitted. Awaiting admin review.",
                link,
            )
            staff(
                f"New {obj.get_donation_type_display().lower()} donation request {obj.donation_code} for {obj.campaign.name}.",
                reverse("management:review", args=["donation", obj.pk]),
            )
        elif changed & {"review_status", "review_reason"}:
            send(
                obj.donor.user_id,
                f"Donation {obj.donation_code}: {obj.get_review_status_display()}. {obj.review_reason}",
                link,
            )
        elif obj.status not in {"STORED", "PARTIALLY_ACCEPTED", "REJECTED"}:
            send(
                obj.donor.user_id,
                f"Donation {obj.donation_code}: {obj.get_status_display()}.",
                link,
            )
    elif sender is DonationItem and "inspection_status" in changed:
        message = f"{obj.donation.donation_code}: {obj.item_name} inspection {obj.get_inspection_status_display()}; {obj.accepted_quantity} {obj.unit} accepted, {obj.rejected_quantity} rejected. {obj.rejection_reason}"
        send(
            obj.donation.donor.user_id,
            message,
            reverse("donor:detail", args=[obj.donation_id]),
        )
        staff(message, reverse("admin:donations_donationitem_change", args=[obj.pk]))
    elif sender is AidRequest:
        link = reverse("seeker:detail", args=[obj.pk])
        if created:
            send(
                obj.seeker.user_id,
                f"Relief request {obj.request_code} submitted. Awaiting admin review.",
                link,
            )
            staff(
                f"New relief request {obj.request_code} for {obj.campaign.name} awaiting review.",
                reverse("management:review", args=["aid", obj.pk]),
            )
        else:
            send(
                obj.seeker.user_id,
                f"Relief request {obj.request_code}: {obj.get_status_display()}; verification {obj.get_verification_status_display()}. {obj.review_reason}",
                link,
            )
    elif sender is AidSeekerProfile and not created:
        send(
            obj.user_id,
            f"Household verification: {obj.get_verification_status_display()}.",
            reverse("accounts:profile"),
        )
        if obj.verification_status == "PENDING":
            staff(
                "A household profile has been resubmitted for verification.",
                reverse("admin:aidseekers_aidseekerprofile_change", args=[obj.pk]),
            )
    elif sender is VolunteerProfile and not created:
        details = []
        if "volunteer_status" in changed:
            details.append(f"status: {obj.get_volunteer_status_display()}")
        if "assigned_area" in changed:
            details.append(f"area: {obj.assigned_area or 'not assigned'}")
        if "assigned_warehouse_id" in changed:
            details.append(f"warehouse: {obj.assigned_warehouse or 'not assigned'}")
        send(
            obj.user_id,
            "Volunteer profile updated — " + "; ".join(details) + ".",
            reverse("volunteer:home"),
        )
    elif sender is DistributionAssignment:
        if before and before["volunteer_id"] != obj.volunteer_id:
            old = VolunteerProfile.objects.using(using).get(pk=before["volunteer_id"])
            send(
                old.user_id,
                "Your previous event assignment has been reassigned.",
                reverse("volunteer:assignments"),
            )
        send(
            obj.volunteer.user_id,
            f"Event assignment {'created' if created else 'updated'}: {obj.distribution_event.name} — {obj.get_status_display()}.",
            reverse("volunteer:assignments"),
        )
        staff(
            f"Volunteer assignment {'created' if created else 'updated'} for {obj.distribution_event.name}: {obj.get_status_display()}.",
            reverse("admin:distributions_distributionassignment_change", args=[obj.pk]),
        )
    elif sender is DistributionEvent and not created:
        volunteers = obj.distributionassignment_set.values_list(
            "volunteer__user_id", flat=True
        ).distinct()
        for user_id in volunteers:
            send(
                user_id,
                f"Event {obj.name} updated: {obj.get_status_display()}. Check the current date and location.",
                reverse("volunteer:assignments"),
            )
        for user_id in (
            obj.distribution_set.filter(status="PLANNED")
            .values_list("beneficiary__user_id", flat=True)
            .distinct()
        ):
            send(
                user_id,
                f"Your relief event {obj.name} has updated scheduling details. Check your delivery plan.",
                reverse("seeker:history"),
            )
    elif sender is Distribution:
        message = f"Delivery {obj.distribution_code}: {'plan created' if created else obj.get_status_display() + ' — plan updated'}."
        send(obj.volunteer.user_id, message, reverse("volunteer:detail", args=[obj.pk]))
        send(obj.beneficiary.user_id, message, reverse("seeker:history"))
        staff(
            message, reverse("admin:distributions_distribution_change", args=[obj.pk])
        )
        if before and before["volunteer_id"] != obj.volunteer_id:
            old = VolunteerProfile.objects.using(using).get(pk=before["volunteer_id"])
            send(
                old.user_id,
                f"Delivery {obj.distribution_code} was reassigned.",
                reverse("volunteer:deliveries"),
            )
        if before and before["beneficiary_id"] != obj.beneficiary_id:
            old = AidSeekerProfile.objects.using(using).get(pk=before["beneficiary_id"])
            send(
                old.user_id,
                f"Delivery plan {obj.distribution_code} was withdrawn. Your relief request remains on record.",
                reverse("seeker:history"),
            )


def assignment_deleted(sender, instance, using="default", **kwargs):
    notify(
        instance.volunteer.user_id,
        f"Your assignment to {instance.distribution_event.name} was removed.",
        reverse("volunteer:assignments"),
        using=using,
    )


for model in TRACKED:
    pre_save.connect(
        remember_state,
        sender=model,
        dispatch_uid=f"notification_before_{model._meta.label_lower}",
    )
    post_save.connect(
        workflow_saved,
        sender=model,
        dispatch_uid=f"notification_after_{model._meta.label_lower}",
    )
post_delete.connect(
    assignment_deleted,
    sender=DistributionAssignment,
    dispatch_uid="notification_assignment_removed",
)

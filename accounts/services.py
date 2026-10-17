from django.db import transaction
from django.utils import timezone

from aidseekers.models import AidSeekerProfile
from audit.services import log
from volunteers.models import VolunteerProfile

from .models import DonorProfile, Role, UserRole
from .permissions import require_staff


@transaction.atomic
def request_role(user, name):
    if name not in {"DONOR", "VOLUNTEER", "AID_SEEKER"}:
        raise ValueError("Invalid role")
    role, _ = Role.objects.get_or_create(
        name=name, defaults={"display_name": name.replace("_", " ").title()}
    )
    membership, created = UserRole.objects.get_or_create(
        user=user,
        role=role,
        defaults={
            "status": "PENDING",
            "approved_at": None,
        },
    )
    profile = {
        "DONOR": DonorProfile,
        "VOLUNTEER": VolunteerProfile,
        "AID_SEEKER": AidSeekerProfile,
    }[name]
    profile.objects.get_or_create(user=user)
    if created:
        log(user, "Role requested", membership)
    return membership


@transaction.atomic
def approve_role(actor, membership):
    require_staff(actor)
    request_role(membership.user, membership.role.name)
    membership.status = "ACTIVE"
    membership.approved_at = timezone.now()
    membership.save()
    if membership.role.name == "VOLUNTEER":
        VolunteerProfile.objects.filter(user=membership.user).update(
            volunteer_status="ACTIVE", approved_by=actor
        )
    log(actor, "Role approval", membership)

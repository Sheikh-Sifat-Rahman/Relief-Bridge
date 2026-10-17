from django.db import transaction
from django.utils import timezone

from .models import AuditLog, CodeSequence


@transaction.atomic
def generate_code(prefix):
    key = f"{prefix}-{timezone.localdate().year}"
    CodeSequence.objects.get_or_create(key=key)
    sequence = CodeSequence.objects.select_for_update().get(key=key)
    sequence.value += 1
    sequence.save(update_fields=["value"])
    return f"{key}-{sequence.value:06d}"


def log(user, action, obj, description=""):
    return AuditLog.objects.create(
        user=user,
        action=action,
        module=obj._meta.app_label,
        object_type=obj._meta.model_name,
        object_id=str(obj.pk),
        description=description,
    )

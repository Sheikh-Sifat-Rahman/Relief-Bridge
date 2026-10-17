from functools import partial

from django.db import transaction

from .models import Notification, User


def notify(recipient_id, message, link="", *, using="default"):
    transaction.on_commit(
        partial(
            Notification.objects.using(using).create,
            recipient_id=recipient_id,
            message=message[:500],
            link=link,
        ),
        using=using,
    )


def notify_staff(message, link="", *, using="default"):
    recipient_ids = list(
        User.objects.using(using)
        .filter(is_active=True, is_staff=True)
        .values_list("pk", flat=True)
    )
    for recipient_id in recipient_ids:
        notify(recipient_id, message, link, using=using)

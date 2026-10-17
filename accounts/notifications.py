from functools import partial

from django.db import transaction

from .models import Notification


def notify(recipient_id, message, link=""):
    transaction.on_commit(
        partial(
            Notification.objects.create,
            recipient_id=recipient_id,
            message=message[:500],
            link=link,
        )
    )

from django.conf import settings
from django.db import models


class CodeSequence(models.Model):
    key = models.CharField(max_length=30, unique=True)
    value = models.PositiveBigIntegerField(default=0)


class AuditLog(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True
    )
    action = models.CharField(max_length=80)
    module = models.CharField(max_length=40)
    object_type = models.CharField(max_length=80)
    object_id = models.CharField(max_length=40)
    description = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-timestamp"]

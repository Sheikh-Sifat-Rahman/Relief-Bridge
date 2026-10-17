from django.db import migrations


def require_approval(apps, schema_editor):
    UserRole = apps.get_model("accounts", "UserRole")
    AuditLog = apps.get_model("audit", "AuditLog")
    approved = set(
        AuditLog.objects.filter(
            action="Role approval", module="accounts", object_type="userrole"
        ).values_list("object_id", flat=True)
    )
    for membership in UserRole.objects.filter(
        role__name="DONOR", status="ACTIVE"
    ).iterator():
        if str(membership.pk) not in approved:
            UserRole.objects.filter(pk=membership.pk).update(
                status="PENDING", approved_at=None
            )


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_userrole_review_reason"),
        ("audit", "0001_initial"),
    ]
    operations = [migrations.RunPython(require_approval, migrations.RunPython.noop)]

from django.db import migrations


def preserve(apps, schema_editor):
    Donation = apps.get_model("donations", "Donation")
    Donation.objects.filter(status="REJECTED").update(review_status="REJECTED")
    Donation.objects.exclude(
        status__in=["SUBMITTED", "COLLECTION_SCHEDULED", "REJECTED"]
    ).update(review_status="APPROVED")
    Donation.objects.filter(payment__payment_status="SUCCESS").update(
        review_status="APPROVED"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("donations", "0002_donation_review_reason_donation_review_status_and_more")
    ]
    operations = [migrations.RunPython(preserve, migrations.RunPython.noop)]

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import User
from accounts.services import request_role
from aidseekers.models import AidRequest
from campaigns.models import DisasterCampaign
from donations.models import Donation, DonationItem
from donations.services import simulate_payment


class Command(BaseCommand):
    help = "Add fictional pending review examples after seed_demo_data. Safe to rerun."

    @transaction.atomic
    def handle(self, *args, **options):
        donor = User.objects.filter(username="demo_donor").first()
        seeker = User.objects.filter(username="demo_seeker").first()
        campaign = DisasterCampaign.objects.filter(status="ACTIVE").first()
        if not donor or not seeker or not campaign:
            raise CommandError("Run seed_demo_data first.")
        pending, created = User.objects.get_or_create(
            username="demo_pending",
            defaults={
                "email": "pending@example.invalid",
                "first_name": "Pending",
                "last_name": "Demo Applicant",
                "phone": "DEMO-000000",
            },
        )
        if created:
            pending.set_unusable_password()
            pending.save()
            request_role(pending, "DONOR")
            request_role(pending, "AID_SEEKER")
        if not DonationItem.objects.filter(item_name="Demo review blankets").exists():
            donation = Donation.objects.create(
                donor=donor.donor_profile, campaign=campaign, donation_type="GOODS"
            )
            DonationItem.objects.create(
                donation=donation,
                category="BLANKET",
                item_name="Demo review blankets",
                quantity=5,
                unit="piece",
                condition="New, demonstration goods",
            )
            simulate_payment(donor.donor_profile, campaign, 500)
        AidRequest.objects.get_or_create(
            seeker=seeker.seeker_profile,
            campaign=campaign,
            explanation="Fictional application for admin review demonstration.",
            defaults={
                "requested_items": "Blankets and drinking water",
                "family_members": 4,
                "children_count": 1,
                "house_damage": "PARTIAL",
            },
        )
        self.stdout.write(
            self.style.SUCCESS(
                "Fictional pending access, donation and relief requests are available in the review centre."
            )
        )

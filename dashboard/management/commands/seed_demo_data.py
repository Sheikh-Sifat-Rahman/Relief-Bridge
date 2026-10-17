import os
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from accounts.services import approve_role, request_role
from aidseekers.models import AidRequest
from campaigns.models import DisasterCampaign
from dashboard.reviews import review_donation
from distributions.models import (
    Distribution,
    DistributionAssignment,
    DistributionEvent,
    DistributionItem,
)
from distributions.services import confirm_distribution
from donations.models import Donation, DonationItem
from donations.services import inspect_goods, simulate_payment
from inventory.models import InventoryItem, Warehouse
from inventory.services import move_stock


class Command(BaseCommand):
    help = "Create clearly fictional demo data. Requires DEMO_PASSWORD. Safe to rerun."

    @transaction.atomic
    def handle(self, *args, **options):
        password = os.getenv("DEMO_PASSWORD")
        if not password:
            raise CommandError("Set DEMO_PASSWORD first.")
        if User.objects.filter(username="demo_admin").exists():
            self.stdout.write("Demo already exists; no changes made.")
            return
        admin = User.objects.create_superuser(
            "demo_admin", "admin@example.invalid", password
        )
        warehouse = Warehouse.objects.create(
            name="Sylhet Community Hub",
            district="Sylhet",
            upazila="Companiganj",
            address="Fictional demonstration warehouse",
        )
        users = {}
        for name, roles in {
            "demo_donor": ["DONOR"],
            "demo_volunteer": ["VOLUNTEER"],
            "demo_seeker": ["AID_SEEKER"],
            "demo_multi": ["DONOR", "VOLUNTEER"],
            "demo_all": ["DONOR", "VOLUNTEER", "AID_SEEKER"],
        }.items():
            user = User.objects.create_user(
                name,
                name + "@example.invalid",
                password,
                first_name=name.replace("demo_", "").title(),
                phone="DEMO-000000",
            )
            users[name] = user
            for role in roles:
                membership = request_role(user, role)
                approve_role(admin, membership)
            if "VOLUNTEER" in roles:
                profile = user.volunteer_profile
                profile.assigned_warehouse = warehouse
                profile.assigned_area = "Companiganj, Sylhet"
                profile.save()
            if "AID_SEEKER" in roles:
                profile = user.seeker_profile
                profile.full_name = "Fictional " + user.first_name + " Household"
                profile.district = "Sylhet"
                profile.upazila = "Companiganj"
                profile.village_or_area = "Demo settlement"
                profile.phone = "DEMO-000000"
                profile.verification_status = "VERIFIED"
                profile.save()
        campaigns = []
        for name, kind, district, upazila, target in [
            ("Rebuild after the floods", "FLOOD", "Sylhet", "Companiganj", 500000),
            ("Stand with coastal families", "CYCLONE", "Khulna", "Dacope", 350000),
            ("A fresh start for families", "FIRE", "Dhaka", "Savar", 200000),
        ]:
            campaigns.append(
                DisasterCampaign.objects.create(
                    name=name,
                    disaster_type=kind,
                    district=district,
                    upazila=upazila,
                    description="Help affected households with safe drinking water, dry food, and essential supplies. Every contribution supports a coordinated community response.",
                    target_amount=target,
                    status="ACTIVE",
                    start_date=timezone.localdate(),
                    created_by=admin,
                )
            )
        campaign = campaigns[0]
        for name, amount in [("demo_donor", 12500), ("demo_all", 7500)]:
            contribution = simulate_payment(users[name].donor_profile, campaign, amount)
            review_donation(admin, contribution.pk, "APPROVE", "Demo admin approval")
        donation = Donation.objects.create(
            donor=users["demo_donor"].donor_profile,
            campaign=campaign,
            donation_type="GOODS",
        )
        goods = DonationItem.objects.create(
            donation=donation,
            category="DRY_FOOD",
            item_name="Rice",
            quantity=100,
            unit="kg",
            condition="Sealed and dry",
        )
        review_donation(admin, donation.pk, "APPROVE", "Demo goods approval")
        inspect_goods(admin, goods.pk, warehouse, 100)
        stock = InventoryItem.objects.get(warehouse=warehouse, item_name="Rice")
        water = InventoryItem.objects.create(
            warehouse=warehouse,
            category="WATER",
            item_name="Drinking water",
            unit="litre",
            minimum_stock_level=50,
        )
        move_stock(
            water.pk,
            500,
            "STOCK_IN",
            admin,
            "DEMO",
            "DEMO-OPENING",
            "Demonstration opening stock",
        )
        aid = AidRequest.objects.create(
            seeker=users["demo_seeker"].seeker_profile,
            campaign=campaign,
            family_members=6,
            children_count=2,
            elderly_count=1,
            house_damage="DESTROYED",
            displaced=True,
            income_lost=True,
            safe_water_available=False,
            requested_items="Rice and drinking water",
            explanation="Fictional flood-affected household.",
            verification_status="VERIFIED",
            verified_by=admin,
            verified_at=timezone.now(),
            status="APPROVED",
        )
        event = DistributionEvent.objects.create(
            campaign=campaign,
            warehouse=warehouse,
            name="Companiganj relief round",
            location="Fictional community centre",
            distribution_date=timezone.now() + timedelta(days=1),
            status="ACTIVE",
            created_by=admin,
        )
        for name in ["demo_volunteer", "demo_all", "demo_multi"]:
            DistributionAssignment.objects.create(
                distribution_event=event, volunteer=users[name].volunteer_profile
            )
        distribution = Distribution.objects.create(
            distribution_event=event,
            aid_request=aid,
            beneficiary=aid.seeker,
            volunteer=users["demo_volunteer"].volunteer_profile,
        )
        DistributionItem.objects.create(
            distribution=distribution, inventory_item=stock, quantity=10, unit="kg"
        )
        confirm_distribution(admin, distribution.pk)
        pending = AidRequest.objects.create(
            seeker=users["demo_all"].seeker_profile,
            campaign=campaign,
            family_members=4,
            children_count=1,
            house_damage="SEVERE",
            income_lost=True,
            requested_items="Food and water",
            explanation="Fictional household awaiting relief.",
            status="APPROVED",
            verification_status="VERIFIED",
            verified_by=admin,
            verified_at=timezone.now(),
        )
        delivery = Distribution.objects.create(
            distribution_event=event,
            aid_request=pending,
            beneficiary=pending.seeker,
            volunteer=users["demo_all"].volunteer_profile,
        )
        DistributionItem.objects.create(
            distribution=delivery, inventory_item=water, quantity=20, unit="litre"
        )
        self.stdout.write(
            self.style.SUCCESS(
                "Demo data created. Usernames: demo_admin, demo_donor, demo_volunteer, demo_seeker, demo_multi, demo_all. Password: your DEMO_PASSWORD."
            )
        )

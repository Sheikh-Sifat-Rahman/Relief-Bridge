from types import SimpleNamespace

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from accounts.services import approve_role, request_role
from aidseekers.models import AidRequest
from aidseekers.services import calculate_priority_score
from audit.models import AuditLog
from campaigns.models import DisasterCampaign
from dashboard.reviews import review_donation
from dashboard.services import research_statistics
from distributions.models import (
    Distribution,
    DistributionAssignment,
    DistributionEvent,
    DistributionItem,
)
from distributions.services import confirm_distribution, duplicate_distributions
from donations.models import Donation, DonationItem
from donations.services import inspect_goods, simulate_payment
from inventory.models import InventoryItem, InventoryTransaction, Warehouse
from inventory.services import move_stock


class SystemTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            "staff", "staff@example.invalid", "Test-password-123"
        )
        cls.donor = cls.make_user("donor", ["DONOR"])
        cls.other = cls.make_user("other", ["DONOR", "AID_SEEKER"])
        cls.volunteer = cls.make_user("volunteer", ["VOLUNTEER"])
        cls.seeker = cls.make_user("seeker", ["AID_SEEKER"])
        cls.all = cls.make_user("all", ["DONOR", "VOLUNTEER", "AID_SEEKER"])
        cls.warehouse = Warehouse.objects.create(
            name="Assigned depot", district="Sylhet", address="Fake"
        )
        cls.other_warehouse = Warehouse.objects.create(
            name="Other depot", district="Dhaka", address="Fake"
        )
        cls.volunteer.volunteer_profile.assigned_warehouse = cls.warehouse
        cls.volunteer.volunteer_profile.save()
        cls.stock = InventoryItem.objects.create(
            warehouse=cls.warehouse, category="DRY_FOOD", item_name="Rice", unit="kg"
        )
        move_stock(cls.stock.pk, 100, "STOCK_IN", cls.admin, "TEST", "OPENING")
        cls.hidden_stock = InventoryItem.objects.create(
            warehouse=cls.other_warehouse,
            category="WATER",
            item_name="Hidden water",
            unit="litre",
        )
        cls.campaign = DisasterCampaign.objects.create(
            name="Flood relief",
            description="Demo",
            district="Sylhet",
            disaster_type="FLOOD",
            start_date=timezone.localdate(),
            status="ACTIVE",
            created_by=cls.admin,
        )
        cls.donation = Donation.objects.create(
            donor=cls.donor.donor_profile, campaign=cls.campaign, donation_type="GOODS"
        )
        cls.aid = AidRequest.objects.create(
            seeker=cls.seeker.seeker_profile,
            campaign=cls.campaign,
            requested_items="Rice",
            explanation="Demo",
            status="APPROVED",
        )
        cls.event = DistributionEvent.objects.create(
            campaign=cls.campaign,
            warehouse=cls.warehouse,
            name="Round one",
            location="Demo",
            distribution_date=timezone.now(),
            created_by=cls.admin,
        )
        DistributionAssignment.objects.create(
            distribution_event=cls.event, volunteer=cls.volunteer.volunteer_profile
        )
        cls.delivery = cls.make_delivery(cls.volunteer, cls.aid)

    @classmethod
    def make_user(cls, name, roles):
        user = User.objects.create_user(
            name, name + "@example.invalid", "Test-password-123"
        )
        for role in roles:
            approve_role(cls.admin, request_role(user, role))
        return user

    @classmethod
    def make_delivery(cls, user, aid, quantity=10):
        delivery = Distribution.objects.create(
            distribution_event=cls.event,
            aid_request=aid,
            beneficiary=aid.seeker,
            volunteer=user.volunteer_profile,
        )
        DistributionItem.objects.create(
            distribution=delivery,
            inventory_item=cls.stock,
            quantity=quantity,
            unit="kg",
        )
        return delivery

    def as_user(self, user):
        self.client.force_login(user)

    def test_registration(self):
        response = self.client.post(
            reverse("accounts:register"),
            {
                "username": "newuser",
                "email": "new@example.invalid",
                "password1": "A-fresh-password-246",
                "password2": "A-fresh-password-246",
                "roles": ["DONOR", "VOLUNTEER"],
            },
        )
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username="newuser")
        self.assertEqual(user.user_roles.get(role__name="DONOR").status, "PENDING")
        self.assertEqual(user.user_roles.get(role__name="VOLUNTEER").status, "PENDING")

    def test_login(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "donor", "password": "Test-password-123"},
        )
        self.assertRedirects(response, reverse("dashboard:home"))

    def test_role_assignment_is_unique(self):
        request_role(self.donor, "DONOR")
        self.assertEqual(self.donor.user_roles.count(), 1)

    def test_multirole_dashboard(self):
        self.as_user(self.all)
        response = self.client.get(reverse("dashboard:home"))
        for title in ["Donor Segment", "Volunteer Segment", "Aid Seeker Segment"]:
            self.assertContains(response, title)

    def test_single_role_dashboard(self):
        self.as_user(self.donor)
        response = self.client.get(reverse("dashboard:home"))
        self.assertContains(response, "Donor Segment")
        self.assertNotContains(response, "Volunteer Segment")

    def test_donor_cannot_open_volunteer(self):
        self.as_user(self.donor)
        self.assertEqual(self.client.get(reverse("volunteer:home")).status_code, 403)

    def test_volunteer_cannot_open_donor(self):
        self.as_user(self.volunteer)
        self.assertEqual(self.client.get(reverse("donor:home")).status_code, 403)

    def test_seeker_cannot_access_warehouse(self):
        self.as_user(self.seeker)
        self.assertEqual(
            self.client.get(reverse("volunteer:warehouse")).status_code, 403
        )

    def test_donor_ownership(self):
        self.as_user(self.other)
        self.assertEqual(
            self.client.get(
                reverse("donor:detail", args=[self.donation.pk])
            ).status_code,
            404,
        )

    def test_seeker_ownership(self):
        self.as_user(self.other)
        self.assertEqual(
            self.client.get(reverse("seeker:detail", args=[self.aid.pk])).status_code,
            404,
        )

    def test_volunteer_only_assigned_distributions(self):
        self.as_user(self.all)
        self.assertEqual(
            self.client.get(
                reverse("volunteer:detail", args=[self.delivery.pk])
            ).status_code,
            404,
        )
        self.as_user(self.volunteer)
        self.assertContains(
            self.client.get(reverse("volunteer:home")), self.delivery.distribution_code
        )

    def test_assigned_warehouse_only(self):
        self.as_user(self.volunteer)
        response = self.client.get(reverse("volunteer:warehouse"))
        self.assertContains(response, "Rice")
        self.assertNotContains(response, "Hidden water")

    def test_inactive_roles(self):
        self.donor.user_roles.update(status="SUSPENDED")
        self.as_user(self.donor)
        self.assertEqual(self.client.get(reverse("donor:home")).status_code, 403)

    def test_no_admin_navigation_even_for_staff(self):
        for user in [self.donor, self.all]:
            self.as_user(user)
            response = self.client.get(reverse("dashboard:home"))
            self.assertNotContains(response, 'href="/management/')

    def test_negative_inventory_prevented(self):
        before = InventoryTransaction.objects.count()
        with self.assertRaises(ValidationError):
            move_stock(self.stock.pk, 101, "STOCK_OUT", self.admin, "TEST", "TOO-MUCH")
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.current_quantity, 100)
        self.assertEqual(InventoryTransaction.objects.count(), before)

    def test_volunteer_cannot_edit_stock(self):
        with self.assertRaises(PermissionDenied):
            move_stock(self.stock.pk, 1, "STOCK_IN", self.volunteer, "TEST", "BAD")

    def test_distribution_deducts_inventory(self):
        confirm_distribution(self.volunteer, self.delivery.pk)
        self.stock.refresh_from_db()
        self.delivery.refresh_from_db()
        self.assertEqual(self.stock.current_quantity, 90)
        self.assertEqual(self.delivery.status, "COMPLETED")
        self.assertTrue(
            InventoryTransaction.objects.filter(
                source_reference=self.delivery.distribution_code,
                transaction_type="STOCK_OUT",
            ).exists()
        )
        self.assertTrue(
            AuditLog.objects.filter(
                action="Distribution completion", object_id=str(self.delivery.pk)
            ).exists()
        )

    def test_distribution_cannot_complete_twice(self):
        confirm_distribution(self.admin, self.delivery.pk)
        with self.assertRaises(ValidationError):
            confirm_distribution(self.admin, self.delivery.pk)
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.current_quantity, 90)

    def test_atomic_rollback_when_second_item_insufficient(self):
        DistributionItem.objects.create(
            distribution=self.delivery,
            inventory_item=self.hidden_stock,
            quantity=1,
            unit="litre",
        )
        with self.assertRaises(ValidationError):
            confirm_distribution(self.admin, self.delivery.pk)
        self.stock.refresh_from_db()
        self.delivery.refresh_from_db()
        self.assertEqual(self.stock.current_quantity, 100)
        self.assertEqual(self.delivery.status, "PLANNED")
        self.assertFalse(
            InventoryTransaction.objects.filter(
                source_reference=self.delivery.distribution_code
            ).exists()
        )

    def test_duplicate_warning_and_staff_override(self):
        confirm_distribution(self.admin, self.delivery.pk)
        second = self.make_delivery(self.volunteer, self.aid)
        self.assertTrue(duplicate_distributions(second).exists())
        with self.assertRaises(ValidationError):
            confirm_distribution(self.volunteer, second.pk)
        with self.assertRaises(ValidationError):
            confirm_distribution(self.admin, second.pk)
        confirm_distribution(
            self.admin, second.pk, "Additional food approved after reassessment"
        )
        second.refresh_from_db()
        self.assertTrue(second.duplicate_warning)
        self.assertTrue(second.override_reason)
        self.assertTrue(
            AuditLog.objects.filter(action="Duplicate-warning override").exists()
        )

    def test_unassigned_user_cannot_confirm(self):
        with self.assertRaises(PermissionDenied):
            confirm_distribution(self.all, self.delivery.pk)

    def test_unapproved_request_cannot_distribute(self):
        self.aid.status = "SUBMITTED"
        self.aid.save()
        with self.assertRaises(ValidationError):
            confirm_distribution(self.admin, self.delivery.pk)

    def test_goods_inspection_traceability(self):
        item = DonationItem.objects.create(
            donation=self.donation,
            category="DRY_FOOD",
            item_name="Rice",
            quantity=20,
            unit="kg",
            condition="Sealed",
        )
        review_donation(self.admin, self.donation.pk, "APPROVE")
        inspect_goods(self.admin, item.pk, self.warehouse, 18, "Two damaged packets")
        self.stock.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(self.stock.current_quantity, 118)
        self.assertEqual(item.rejected_quantity, 2)
        with self.assertRaises(ValidationError):
            inspect_goods(self.admin, item.pk, self.warehouse, 18)

    def test_simulation_updates_campaign_once(self):
        donation = simulate_payment(self.donor.donor_profile, self.campaign, 250)
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.collected_amount, 0)
        review_donation(self.admin, donation.pk, "APPROVE")
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.collected_amount, 250)
        self.assertEqual(donation.payment.payment_method, "SIMULATION")
        self.assertTrue(donation.payment.transaction_reference.startswith("SIM-"))

    def test_csrf_is_required_for_mutation(self):
        from django.test import Client

        client = Client(enforce_csrf_checks=True)
        client.force_login(self.donor)
        self.assertEqual(
            client.post(
                reverse("donor:money"), {"campaign": self.campaign.pk, "amount": "100"}
            ).status_code,
            403,
        )

    def test_goods_submission(self):
        self.as_user(self.donor)
        response = self.client.post(
            reverse("donor:goods"),
            {
                "campaign": self.campaign.pk,
                "category": "BLANKET",
                "item_name": "Blanket",
                "quantity": "2",
                "unit": "piece",
                "condition": "New",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            DonationItem.objects.filter(
                donation__donor__user=self.donor, item_name="Blanket"
            ).exists()
        )

    def test_aid_submission_is_advisory(self):
        self.as_user(self.seeker)
        response = self.client.post(
            reverse("seeker:create"),
            {
                "campaign": self.campaign.pk,
                "family_members": 6,
                "children_count": 2,
                "elderly_count": 1,
                "house_damage": "DESTROYED",
                "displaced": "on",
                "income_lost": "on",
                "requested_items": "Food",
                "explanation": "Demo",
            },
        )
        self.assertEqual(response.status_code, 302)
        obj = AidRequest.objects.filter(seeker__user=self.seeker).latest("pk")
        self.assertEqual(obj.priority_level, "CRITICAL")
        self.assertEqual(obj.status, "SUBMITTED")

    def test_private_views_require_login(self):
        for route in ["dashboard:home", "donor:home", "seeker:home", "volunteer:home"]:
            self.assertEqual(self.client.get(reverse(route)).status_code, 302)

    def test_all_public_and_role_templates_render(self):
        for route in [
            "home",
            "transparency",
            "campaigns:list",
            "accounts:login",
            "accounts:register",
        ]:
            self.assertEqual(self.client.get(reverse(route)).status_code, 200, route)
        self.as_user(self.all)
        for route in [
            "accounts:profile",
            "accounts:password",
            "dashboard:home",
            "donor:home",
            "donor:profile",
            "donor:goods",
            "donor:money",
            "seeker:home",
            "accounts:household",
            "seeker:create",
            "volunteer:home",
            "volunteer:warehouse",
        ]:
            self.assertEqual(self.client.get(reverse(route)).status_code, 200, route)
        self.assertEqual(
            self.client.get(
                reverse("campaigns:detail", args=[self.campaign.pk])
            ).status_code,
            200,
        )

    def test_seeker_profile_redirects_to_household(self):
        self.as_user(self.seeker)
        self.assertRedirects(
            self.client.get(reverse("seeker:profile")), reverse("accounts:household")
        )

    def test_pending_household_completion(self):
        user = User.objects.create_user(
            "pending", "pending@example.invalid", "Test-password-123"
        )
        request_role(user, "AID_SEEKER")
        self.as_user(user)
        self.assertEqual(
            self.client.get(reverse("accounts:household")).status_code, 200
        )
        self.assertEqual(self.client.get(reverse("seeker:home")).status_code, 403)

    def test_public_never_exposes_identity(self):
        for route in ["home", "transparency", "campaigns:list"]:
            response = self.client.get(reverse(route))
            self.assertNotContains(response, self.seeker.email)
            self.assertNotContains(response, self.donor.email)

    def test_research_traceability(self):
        self.assertEqual(research_statistics()["traceability_percent"], 100)

    def test_management_nonstaff_rejected(self):
        self.as_user(self.donor)
        self.assertEqual(self.client.get("/management/").status_code, 403)

    def test_admin_workflow_pages_render(self):
        self.as_user(self.admin)
        for url in [
            "/management/",
            reverse("admin:inventory_movement", args=[self.stock.pk]),
            reverse("admin:distribution_confirm", args=[self.delivery.pk]),
            reverse("admin:distributions_distribution_change", args=[self.delivery.pk]),
        ]:
            self.assertEqual(self.client.get(url).status_code, 200, url)


class PriorityTests(TestCase):
    def score(self, **kwargs):
        values = dict(
            house_damage="NONE",
            income_lost=False,
            displaced=False,
            safe_water_available=True,
            children_count=0,
            elderly_count=0,
        )
        values.update(kwargs)
        return calculate_priority_score(SimpleNamespace(**values))

    def test_zero(self):
        self.assertEqual(self.score(), (0, "LOW"))

    def test_damage_weights(self):
        for damage, score in [("PARTIAL", 10), ("SEVERE", 20), ("DESTROYED", 30)]:
            self.assertEqual(self.score(house_damage=damage)[0], score)

    def test_caps(self):
        self.assertEqual(
            self.score(
                house_damage="DESTROYED",
                income_lost=True,
                displaced=True,
                safe_water_available=False,
                children_count=20,
                elderly_count=20,
            ),
            (100, "CRITICAL"),
        )

    def test_thresholds(self):
        self.assertEqual(self.score(house_damage="DESTROYED"), (30, "MEDIUM"))
        self.assertEqual(
            self.score(house_damage="DESTROYED", income_lost=True), (50, "HIGH")
        )
        self.assertEqual(
            self.score(
                house_damage="DESTROYED",
                income_lost=True,
                displaced=True,
                elderly_count=1,
            ),
            (70, "CRITICAL"),
        )

    def test_advisory_only(self):
        self.assertEqual(self.score(children_count=6, elderly_count=4), (30, "MEDIUM"))

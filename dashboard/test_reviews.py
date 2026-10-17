from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from accounts.services import request_role
from aidseekers.models import AidRequest
from audit.models import AuditLog
from campaigns.models import DisasterCampaign
from donations.models import Donation, DonationItem
from donations.services import inspect_goods, simulate_payment
from inventory.models import InventoryTransaction, Warehouse

from .reviews import review_aid, review_donation, review_role


class AdminReviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            "review_admin", "review@example.invalid", "Review-password-123"
        )
        cls.user = User.objects.create_user(
            "applicant", "applicant@example.invalid", "Applicant-password-123"
        )
        cls.donor_role = request_role(cls.user, "DONOR")
        cls.seeker_role = request_role(cls.user, "AID_SEEKER")
        cls.campaign = DisasterCampaign.objects.create(
            name="Review test",
            description="Demo",
            district="Sylhet",
            disaster_type="FLOOD",
            status="ACTIVE",
            start_date=timezone.localdate(),
            created_by=cls.admin,
        )
        cls.warehouse = Warehouse.objects.create(
            name="Review warehouse", district="Sylhet", address="Demo"
        )

    def approved_donor(self):
        review_role(self.admin, self.donor_role.pk, "APPROVE")
        return self.user.donor_profile

    def donation(self):
        obj = Donation.objects.create(
            donor=self.user.donor_profile, campaign=self.campaign, donation_type="GOODS"
        )
        DonationItem.objects.create(
            donation=obj,
            category="BLANKET",
            item_name="Blanket",
            quantity=2,
            unit="piece",
            condition="New",
        )
        return obj

    def aid(self):
        return AidRequest.objects.create(
            seeker=self.user.seeker_profile,
            campaign=self.campaign,
            requested_items="Food",
            explanation="Demo",
        )

    def test_every_new_role_pending(self):
        self.assertEqual(self.donor_role.status, "PENDING")
        self.assertEqual(self.seeker_role.status, "PENDING")
        self.assertIsNone(self.donor_role.approved_at)

    def test_unapproved_user_cannot_get_or_post_submissions(self):
        self.client.force_login(self.user)
        for route in ["donor:goods", "donor:money", "seeker:create"]:
            self.assertEqual(self.client.get(reverse(route)).status_code, 403)
            self.assertEqual(
                self.client.post(
                    reverse(route), {"campaign": self.campaign.pk, "amount": "100"}
                ).status_code,
                403,
            )
        self.assertEqual(Donation.objects.count(), 0)
        self.assertEqual(AidRequest.objects.count(), 0)

    def test_money_service_requires_approved_donor(self):
        with self.assertRaises(PermissionDenied):
            simulate_payment(self.user.donor_profile, self.campaign, 100)

    def test_admin_email_login(self):
        response = self.client.post(
            reverse("management:login"),
            {"username": "REVIEW@example.invalid", "password": "Review-password-123"},
        )
        self.assertRedirects(response, reverse("management:home"))

    def test_username_not_accepted_in_admin_email_form(self):
        response = self.client.post(
            reverse("management:login"),
            {"username": "review_admin", "password": "Review-password-123"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_nonstaff_cannot_use_admin_login(self):
        response = self.client.post(
            reverse("management:login"),
            {"username": self.user.email, "password": "Applicant-password-123"},
        )
        self.assertContains(response, "Use an administrator account")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_wrong_admin_password(self):
        response = self.client.post(
            reverse("management:login"),
            {"username": self.admin.email, "password": "wrong"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_review_requires_staff_and_login(self):
        url = reverse("management:review", args=["role", self.donor_role.pk])
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(
            self.client.post(url, {"decision": "APPROVE"}).status_code, 403
        )
        for service, args in [
            (review_role, [self.donor_role.pk]),
            (review_donation, [self.donation().pk]),
            (review_aid, [self.aid().pk]),
        ]:
            with self.assertRaises(PermissionDenied):
                service(self.user, *args, "APPROVE")

    def test_accept_role_enables_submission(self):
        self.approved_donor()
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("donor:money")).status_code, 200)
        self.assertEqual(self.client.get(reverse("seeker:create")).status_code, 403)

    def test_reject_role_keeps_access_blocked(self):
        review_role(
            self.admin, self.donor_role.pk, "REJECT", "Please provide contact details"
        )
        self.donor_role.refresh_from_db()
        self.assertEqual(self.donor_role.status, "REJECTED")
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("donor:goods")).status_code, 403)
        self.assertContains(
            self.client.get(reverse("dashboard:home")), "Please provide contact details"
        )

    def test_rejection_reason_required(self):
        with self.assertRaises(ValidationError):
            review_role(self.admin, self.donor_role.pk, "REJECT")
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("management:review", args=["role", self.donor_role.pk]),
            {"decision": "REJECT"},
        )
        self.assertContains(response, "A reason is required")
        self.donor_role.refresh_from_db()
        self.assertEqual(self.donor_role.status, "PENDING")

    def test_get_review_does_not_accept(self):
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("management:review", args=["role", self.donor_role.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.donor_role.refresh_from_db()
        self.assertEqual(self.donor_role.status, "PENDING")

    def test_money_waits_for_admin_then_counts_once(self):
        obj = simulate_payment(self.approved_donor(), self.campaign, 250)
        self.assertEqual(obj.review_status, "PENDING")
        self.assertEqual(obj.payment.payment_status, "PENDING")
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.collected_amount, 0)
        review_donation(self.admin, obj.pk, "APPROVE", "Accepted for campaign")
        self.campaign.refresh_from_db()
        obj.refresh_from_db()
        self.assertEqual(self.campaign.collected_amount, 250)
        self.assertEqual(obj.payment.payment_status, "SUCCESS")
        self.assertEqual(obj.reviewed_by, self.admin)
        with self.assertRaises(ValidationError):
            review_donation(self.admin, obj.pk, "APPROVE")
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.collected_amount, 250)

    def test_rejected_money_not_counted(self):
        obj = simulate_payment(self.approved_donor(), self.campaign, 100)
        review_donation(self.admin, obj.pk, "REJECT", "Duplicate pledge")
        obj.refresh_from_db()
        self.campaign.refresh_from_db()
        self.assertEqual(obj.review_status, "REJECTED")
        self.assertEqual(obj.payment.payment_status, "FAILED")
        self.assertEqual(self.campaign.collected_amount, 0)

    def test_pending_or_rejected_goods_cannot_enter_stock(self):
        obj = self.donation()
        item = obj.items.get()
        with self.assertRaises(ValidationError):
            inspect_goods(self.admin, item.pk, self.warehouse, 2)
        review_donation(self.admin, obj.pk, "REJECT", "Unsuitable goods")
        with self.assertRaises(ValidationError):
            inspect_goods(self.admin, item.pk, self.warehouse, 2)
        self.assertEqual(InventoryTransaction.objects.count(), 0)

    def test_approved_goods_require_inspection(self):
        obj = self.donation()
        review_donation(self.admin, obj.pk, "APPROVE")
        self.assertEqual(InventoryTransaction.objects.count(), 0)
        inspect_goods(self.admin, obj.items.get().pk, self.warehouse, 2)
        self.assertEqual(InventoryTransaction.objects.count(), 1)

    def test_relief_acceptance_and_rejection(self):
        obj = self.aid()
        review_aid(self.admin, obj.pk, "APPROVE", "Household verified")
        obj.refresh_from_db()
        self.assertEqual(obj.status, "APPROVED")
        self.assertEqual(obj.reviewed_by, self.admin)
        self.assertEqual(obj.verification_status, "VERIFIED")
        with self.assertRaises(ValidationError):
            review_aid(self.admin, obj.pk, "REJECT", "Changed decision")
        other = self.aid()
        review_aid(self.admin, other.pk, "REJECT", "Need more information")
        other.refresh_from_db()
        self.assertEqual(other.status, "REJECTED")
        self.assertEqual(other.review_reason, "Need more information")

    def test_review_centre_profile_and_decisions(self):
        donation = self.donation()
        aid = self.aid()
        self.client.force_login(self.admin)
        response = self.client.get(reverse("management:home"))
        self.assertContains(response, donation.donation_code)
        self.assertContains(response, aid.request_code)
        self.assertContains(response, self.user.email)
        for kind, obj in [
            ("role", self.donor_role),
            ("donation", donation),
            ("aid", aid),
        ]:
            url = reverse("management:review", args=[kind, obj.pk])
            self.assertEqual(self.client.get(url).status_code, 200)
            self.assertRedirects(
                self.client.post(url, {"decision": "APPROVE", "reason": "Reviewed"}),
                reverse("management:home"),
            )
        self.assertEqual(
            self.client.get(reverse("management:profile")).status_code, 200
        )
        self.assertTrue(
            AuditLog.objects.filter(
                action="Donation acceptance", user=self.admin
            ).exists()
        )

    def test_review_post_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(
            client.post(
                reverse("management:review", args=["role", self.donor_role.pk]),
                {"decision": "APPROVE"},
            ).status_code,
            403,
        )

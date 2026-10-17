from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Notification, User
from accounts.services import request_role
from aidseekers.models import AidRequest
from dashboard import tests as fixtures
from dashboard.reviews import review_aid, review_donation, review_role
from distributions.models import DistributionAssignment
from distributions.services import (
    cancel_distribution,
    confirm_distribution,
    reserve_distribution,
)
from donations.models import Donation, DonationItem
from donations.services import inspect_goods, simulate_payment


class NotificationWorkflowTests(TestCase):
    setUpTestData = classmethod(fixtures.SystemTests.setUpTestData.__func__)
    make_user = classmethod(fixtures.SystemTests.make_user.__func__)
    make_delivery = classmethod(fixtures.SystemTests.make_delivery.__func__)

    def notices(self, user):
        return Notification.objects.filter(recipient=user)

    def test_new_goods_request_notifies_donor_and_all_active_admins(self):
        second = User.objects.create_user(
            "second_admin", "second@example.invalid", is_staff=True
        )
        inactive = User.objects.create_user(
            "inactive_admin", "inactive@example.invalid", is_staff=True, is_active=False
        )
        with self.captureOnCommitCallbacks(execute=True):
            obj = Donation.objects.create(
                donor=self.donor.donor_profile,
                campaign=self.campaign,
                donation_type="GOODS",
            )
            self.assertFalse(Notification.objects.exists())
        for user in [self.admin, second, self.donor]:
            self.assertEqual(self.notices(user).count(), 1)
            self.assertIn(obj.donation_code, self.notices(user).get().message)
        self.assertFalse(self.notices(inactive).exists())
        self.assertFalse(self.notices(self.other).exists())
        self.assertEqual(
            self.notices(self.admin).get().link,
            reverse("management:review", args=["donation", obj.pk]),
        )

    def test_money_submission_and_approval_notify_once_per_event(self):
        with self.captureOnCommitCallbacks(execute=True):
            obj = simulate_payment(self.donor.donor_profile, self.campaign, 50)
        self.assertEqual(self.notices(self.donor).count(), 1)
        with self.captureOnCommitCallbacks(execute=True):
            review_donation(self.admin, obj.pk, "APPROVE", "Accepted for flood relief")
        self.assertEqual(self.notices(self.donor).count(), 2)
        self.assertIn(
            "Accepted for flood relief", self.notices(self.donor).first().message
        )
        with self.captureOnCommitCallbacks(execute=True):
            with self.assertRaises(ValidationError):
                review_donation(self.admin, obj.pk, "APPROVE")
        self.assertEqual(self.notices(self.donor).count(), 2)

    def test_donation_rejection_includes_reason(self):
        with self.captureOnCommitCallbacks(execute=True):
            review_donation(
                self.admin, self.donation.pk, "REJECT", "Goods are not suitable"
            )
        notice = self.notices(self.donor).get()
        self.assertIn("Rejected", notice.message)
        self.assertIn("Goods are not suitable", notice.message)

    def test_aid_submission_and_decision(self):
        with self.captureOnCommitCallbacks(execute=True):
            aid = AidRequest.objects.create(
                seeker=self.seeker.seeker_profile,
                campaign=self.campaign,
                requested_items="Water",
                explanation="Test",
            )
        self.assertEqual(self.notices(self.seeker).count(), 1)
        self.assertEqual(
            self.notices(self.admin).get().link,
            reverse("management:review", args=["aid", aid.pk]),
        )
        with self.captureOnCommitCallbacks(execute=True):
            review_aid(self.admin, aid.pk, "REJECT", "Please correct the request")
        self.assertEqual(self.notices(self.seeker).count(), 2)
        self.assertIn(
            "Please correct the request", self.notices(self.seeker).first().message
        )

    def test_role_request_and_decision_for_pending_user(self):
        user = User.objects.create_user("new", "new@example.invalid")
        with self.captureOnCommitCallbacks(execute=True):
            membership = request_role(user, "VOLUNTEER")
        self.assertEqual(self.notices(user).count(), 1)
        self.assertEqual(self.notices(self.admin).count(), 1)
        with self.captureOnCommitCallbacks(execute=True):
            review_role(self.admin, membership.pk, "APPROVE")
        self.assertEqual(self.notices(user).count(), 2)
        self.assertIn("ACTIVE", self.notices(user).first().message)

    def test_operations_role_changes_notify_without_review_service(self):
        membership = self.donor.user_roles.get(role__name="DONOR")
        with self.captureOnCommitCallbacks(execute=True):
            membership.status = "SUSPENDED"
            membership.review_reason = "Please update your profile"
            membership.save()
            membership.save()
        self.assertEqual(self.notices(self.donor).count(), 1)
        self.assertIn(
            "Please update your profile", self.notices(self.donor).get().message
        )

    def test_inspection_notifies_owner_and_admin(self):
        self.donation.review_status = "APPROVED"
        self.donation.save()
        item = DonationItem.objects.create(
            donation=self.donation,
            category="DRY_FOOD",
            item_name="Rice",
            unit="kg",
            quantity=10,
            condition="New",
        )
        with self.captureOnCommitCallbacks(execute=True):
            inspect_goods(self.admin, item.pk, self.warehouse, 8, "Two damaged")
        self.assertEqual(self.notices(self.donor).count(), 1)
        self.assertIn("Two damaged", self.notices(self.donor).get().message)
        self.assertEqual(self.notices(self.admin).count(), 1)

    def test_assignment_changes_notify_old_and_new_volunteers(self):
        assignment = DistributionAssignment.objects.get(distribution_event=self.event)
        with self.captureOnCommitCallbacks(execute=True):
            assignment.volunteer = self.all.volunteer_profile
            assignment.save()
        self.assertEqual(self.notices(self.volunteer).count(), 1)
        self.assertEqual(self.notices(self.all).count(), 1)
        self.assertIn("reassigned", self.notices(self.volunteer).get().message)
        with self.captureOnCommitCallbacks(execute=True):
            assignment.delete()
        self.assertIn("removed", self.notices(self.all).first().message)

    def test_volunteer_area_warehouse_and_event_updates(self):
        with self.captureOnCommitCallbacks(execute=True):
            profile = self.volunteer.volunteer_profile
            profile.assigned_area = "New area"
            profile.assigned_warehouse = self.other_warehouse
            profile.save()
            self.event.distribution_date = timezone.now() + timedelta(days=2)
            self.event.save()
        self.assertEqual(self.notices(self.volunteer).count(), 2)
        self.assertTrue(
            self.notices(self.volunteer).filter(message__contains="New area").exists()
        )
        self.assertEqual(self.notices(self.seeker).count(), 1)

    def test_scheduling_and_cancellation_notify_participants_and_admin(self):
        with self.captureOnCommitCallbacks(execute=True):
            reserve_distribution(self.admin, self.delivery.pk)
            cancel_distribution(self.admin, self.delivery.pk)
        for user in [self.admin, self.seeker, self.volunteer]:
            self.assertEqual(self.notices(user).count(), 2)
        self.assertFalse(self.notices(self.other).exists())

    def test_delivery_completion_notifies_admin_volunteer_and_seeker(self):
        with self.captureOnCommitCallbacks(execute=True):
            confirm_distribution(self.volunteer, self.delivery.pk)
        self.assertEqual(self.notices(self.volunteer).count(), 1)
        self.assertEqual(self.notices(self.admin).count(), 1)
        self.assertTrue(
            self.notices(self.seeker)
            .filter(message__contains=self.delivery.distribution_code)
            .exists()
        )

    def test_rollback_has_no_notifications(self):
        with self.captureOnCommitCallbacks(execute=True):
            try:
                with transaction.atomic():
                    Donation.objects.create(
                        donor=self.donor.donor_profile,
                        campaign=self.campaign,
                        donation_type="GOODS",
                    )
                    raise ValueError("cancel")
            except ValueError:
                pass
        self.assertFalse(Notification.objects.exists())

    def test_all_roles_and_pending_users_can_read_own_inbox(self):
        pending = User.objects.create_user("pending", "pending@example.invalid")
        for user in [
            self.admin,
            self.donor,
            self.seeker,
            self.volunteer,
            self.all,
            pending,
        ]:
            with self.subTest(user=user.username):
                Notification.objects.create(
                    recipient=user, message=f"Private update for {user.username}"
                )
                self.client.force_login(user)
                response = self.client.get(reverse("accounts:notifications"))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, f"Private update for {user.username}")
                self.assertEqual(
                    list(response.context["page"]), list(self.notices(user))
                )
                if not user.is_staff:
                    self.assertContains(
                        self.client.get(reverse("dashboard:home")), "My notifications"
                    )

    def test_unread_filter_and_mark_all_do_not_affect_other_users(self):
        Notification.objects.create(
            recipient=self.donor, message="Read", read_at=timezone.now()
        )
        Notification.objects.create(recipient=self.donor, message="Unread")
        other = Notification.objects.create(recipient=self.other, message="Private")
        self.client.force_login(self.donor)
        url = reverse("accounts:notifications")
        response = self.client.get(url, {"filter": "unread"})
        self.assertEqual(len(response.context["page"]), 1)
        self.assertEqual(response.context["unread_count"], 1)
        self.client.post(url)
        self.assertFalse(self.notices(self.donor).filter(read_at__isnull=True).exists())
        other.refresh_from_db()
        self.assertIsNone(other.read_at)

    def test_login_and_csrf_required(self):
        url = reverse("accounts:notifications")
        self.assertEqual(self.client.get(url).status_code, 302)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.donor)
        self.assertEqual(client.post(url).status_code, 403)

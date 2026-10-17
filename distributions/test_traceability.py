from datetime import timedelta
from decimal import Decimal
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Notification
from accounts.notifications import notify
from dashboard import tests as fixtures
from distributions.models import DistributionAllocation, DistributionItem
from distributions.services import (
    cancel_distribution,
    confirm_distribution,
    reserve_distribution,
)
from donations.models import DonationItem
from donations.services import inspect_goods
from inventory.models import InventoryBatch, InventoryItem, Warehouse
from inventory.services import move_stock


class TraceabilityTests(TestCase):
    setUpTestData = classmethod(fixtures.SystemTests.setUpTestData.__func__)
    make_user = classmethod(fixtures.SystemTests.make_user.__func__)
    make_delivery = classmethod(fixtures.SystemTests.make_delivery.__func__)

    def receive(self, quantity=20, expiry=None):
        self.donation.review_status = "APPROVED"
        self.donation.save()
        item = DonationItem.objects.create(
            donation=self.donation,
            category="DRY_FOOD",
            item_name="Rice",
            unit="kg",
            quantity=quantity,
            condition="New",
            expiration_date=expiry,
        )
        inspect_goods(self.admin, item.pk, self.warehouse, quantity)
        return item.batch

    def test_receipt_keeps_source_and_expiration(self):
        expiry = timezone.localdate() + timedelta(days=5)
        batch = self.receive(expiry=expiry)
        self.assertEqual(batch.donation_item.donation, self.donation)
        self.assertEqual(batch.expiration_date, expiry)
        self.assertEqual(batch.remaining_quantity, 20)
        with self.assertRaises(ValidationError):
            inspect_goods(self.admin, batch.donation_item_id, self.warehouse, 20)
        self.assertEqual(
            InventoryBatch.objects.filter(donation_item=batch.donation_item).count(), 1
        )

    def test_expired_goods_cannot_be_received(self):
        with self.assertRaises(ValidationError):
            self.receive(expiry=timezone.localdate() - timedelta(days=1))
        self.assertFalse(InventoryBatch.objects.filter(source="DONATION").exists())

    def test_earliest_expiry_reserved_first_and_no_stock_deducted(self):
        later = self.receive(expiry=timezone.localdate() + timedelta(days=10))
        first = self.receive(expiry=timezone.localdate() + timedelta(days=2))
        reserve_distribution(self.admin, self.delivery.pk)
        self.assertEqual(DistributionAllocation.objects.get().batch_id, first.pk)
        later.refresh_from_db()
        first.refresh_from_db()
        self.stock.refresh_from_db()
        self.assertEqual(first.reserved_quantity, 10)
        self.assertEqual(later.reserved_quantity, 0)
        self.assertEqual(self.stock.current_quantity, 140)
        self.assertEqual(self.stock.available_quantity, 130)

    def test_reservations_cannot_overbook_and_failure_rolls_back(self):
        self.delivery.items.update(quantity=80)
        reserve_distribution(self.admin, self.delivery.pk)
        other = self.make_delivery(self.volunteer, self.aid, 30)
        with self.assertRaises(ValidationError):
            reserve_distribution(self.admin, other.pk)
        self.assertFalse(
            DistributionAllocation.objects.filter(
                distribution_item__distribution=other
            ).exists()
        )
        self.assertEqual(self.stock.reserved_quantity, 80)
        with self.assertRaises(ValidationError):
            reserve_distribution(self.admin, self.delivery.pk)

    def test_manual_removal_preserves_reserved_stock(self):
        self.delivery.items.update(quantity=90)
        reserve_distribution(self.admin, self.delivery.pk)
        with self.assertRaises(ValidationError):
            move_stock(self.stock.pk, 11, "STOCK_OUT", self.admin, "TEST", "remove")
        move_stock(self.stock.pk, -10, "ADJUSTMENT", self.admin, "TEST", "correction")
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.current_quantity, 90)
        self.assertEqual(self.stock.available_quantity, 0)

    def test_cancellation_releases_and_preserves_history(self):
        reserve_distribution(self.admin, self.delivery.pk)
        cancel_distribution(self.admin, self.delivery.pk)
        self.assertEqual(self.stock.reserved_quantity, 0)
        self.assertEqual(self.stock.available_quantity, 100)
        self.assertEqual(DistributionAllocation.objects.get().status, "RELEASED")
        with self.assertRaises(ValidationError):
            confirm_distribution(self.admin, self.delivery.pk)
        with self.assertRaises(ValidationError):
            cancel_distribution(self.admin, self.delivery.pk)

    def test_delivery_consumes_reserved_batch_once(self):
        batch = self.receive(expiry=timezone.localdate() + timedelta(days=2))
        reserve_distribution(self.admin, self.delivery.pk)
        confirm_distribution(self.volunteer, self.delivery.pk)
        batch.refresh_from_db()
        self.assertEqual(batch.remaining_quantity, 10)
        self.assertEqual(batch.reserved_quantity, 0)
        self.assertEqual(DistributionAllocation.objects.get().status, "DELIVERED")
        with self.assertRaises(ValidationError):
            confirm_distribution(self.volunteer, self.delivery.pk)
        self.assertEqual(
            self.stock.transactions.filter(transaction_type="STOCK_OUT").count(), 1
        )

    def test_expiry_after_reservation_blocks_delivery_without_deduction(self):
        batch = self.receive(expiry=timezone.localdate())
        reserve_distribution(self.admin, self.delivery.pk)
        with patch(
            "distributions.services.timezone.localdate",
            return_value=timezone.localdate() + timedelta(days=1),
        ):
            with self.assertRaises(ValidationError):
                confirm_distribution(self.admin, self.delivery.pk)
        batch.refresh_from_db()
        self.assertEqual(batch.remaining_quantity, 20)
        self.assertEqual(batch.reserved_quantity, 10)
        self.assertEqual(DistributionAllocation.objects.get().status, "RESERVED")
        cancel_distribution(self.admin, self.delivery.pk)

    def test_expired_batches_are_excluded_from_reservation(self):
        self.stock.batches.update(
            expiration_date=timezone.localdate() - timedelta(days=1)
        )
        with self.assertRaises(ValidationError):
            reserve_distribution(self.admin, self.delivery.pk)
        self.assertEqual(self.stock.available_quantity, 0)

    def test_insufficient_second_item_rolls_back_first_reservation(self):
        DistributionItem.objects.create(
            distribution=self.delivery,
            inventory_item=self.hidden_stock,
            quantity=1,
            unit="litre",
        )
        with self.assertRaises(ValidationError):
            reserve_distribution(self.admin, self.delivery.pk)
        self.assertEqual(self.stock.reserved_quantity, 0)
        self.assertEqual(DistributionAllocation.objects.count(), 0)

    def test_partial_delivery_timeline_has_no_recipient_details(self):
        batch = self.receive(expiry=timezone.localdate() + timedelta(days=2))
        confirm_distribution(self.admin, self.delivery.pk)
        self.client.force_login(self.donor)
        response = self.client.get(reverse("donor:detail", args=[self.donation.pk]))
        self.assertContains(response, "Donation journey")
        self.assertContains(response, "Delivered")
        self.assertEqual(response.context["batches"][0].delivered_quantity, 10)
        self.assertEqual(response.context["batches"][0].remaining_quantity, 10)
        self.assertNotContains(response, self.seeker.email)
        self.assertNotContains(response, self.delivery.distribution_code)
        self.client.force_login(self.other)
        self.assertEqual(
            self.client.get(
                reverse("donor:detail", args=[self.donation.pk])
            ).status_code,
            404,
        )
        self.assertEqual(batch.donation_item.donation_id, self.donation.pk)

    def test_event_cancellation_releases_all_reservations(self):
        from django.contrib import admin

        from distributions.admin import EventAdmin
        from distributions.models import DistributionEvent

        reserve_distribution(self.admin, self.delivery.pk)
        self.event.status = "CANCELLED"
        EventAdmin(DistributionEvent, admin.site).save_model(
            SimpleNamespace(user=self.admin), self.event, None, True
        )
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.status, "CANCELLED")
        self.assertEqual(self.stock.reserved_quantity, 0)

    def test_stock_must_last_until_scheduled_event(self):
        self.stock.batches.update(
            expiration_date=timezone.localdate() + timedelta(days=1)
        )
        self.event.distribution_date = timezone.now() + timedelta(days=3)
        self.event.save()
        with self.assertRaises(ValidationError):
            reserve_distribution(self.admin, self.delivery.pk)
        self.assertEqual(self.stock.reserved_quantity, 0)

    def test_reserved_admin_page_locks_lines_and_shows_state(self):
        reserve_distribution(self.admin, self.delivery.pk)
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("admin:distributions_distribution_change", args=[self.delivery.pk])
        )
        self.assertContains(response, "Reserved")
        self.assertNotContains(response, 'name="items-0-quantity"')

    def test_reservation_and_cancel_require_staff(self):
        for service in [reserve_distribution, cancel_distribution]:
            with self.assertRaises(PermissionDenied):
                service(self.volunteer, self.delivery.pk)

    def test_schedule_admin_get_does_not_mutate_post_reserves(self):
        self.client.force_login(self.admin)
        url = reverse("admin:distribution_schedule", args=[self.delivery.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(DistributionAllocation.objects.count(), 0)
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertEqual(self.stock.reserved_quantity, 10)
        self.assertEqual(
            self.client.post(
                reverse("admin:distribution_cancel", args=[self.delivery.pk])
            ).status_code,
            302,
        )
        self.assertEqual(self.stock.reserved_quantity, 0)

    def test_notifications_only_after_commit_and_no_rollback_notifications(self):
        with self.captureOnCommitCallbacks(execute=True):
            reserve_distribution(self.admin, self.delivery.pk)
            self.assertFalse(Notification.objects.exists())
        self.assertEqual(Notification.objects.filter(recipient=self.seeker).count(), 1)
        with self.captureOnCommitCallbacks(execute=True):
            try:
                with transaction.atomic():
                    notify(self.donor.pk, "Must not be sent")
                    raise ValidationError("rollback")
            except ValidationError:
                pass
        self.assertFalse(
            Notification.objects.filter(message="Must not be sent").exists()
        )

    def test_notification_ownership_and_read_tracking(self):
        mine = Notification.objects.create(
            recipient=self.donor, message="Your goods were accepted"
        )
        private = Notification.objects.create(
            recipient=self.other, message="Private update"
        )
        self.client.force_login(self.donor)
        url = reverse("accounts:notifications")
        response = self.client.get(url)
        self.assertContains(response, mine.message)
        self.assertNotContains(response, private.message)
        self.client.post(url, {"notification_id": private.pk})
        private.refresh_from_db()
        self.assertIsNone(private.read_at)
        self.client.post(url, {"notification_id": mine.pk})
        mine.refresh_from_db()
        self.assertIsNotNone(mine.read_at)


class OpeningBalanceTests(TestCase):
    def test_migration_preserves_balance_without_inventing_donor(self):
        warehouse = Warehouse.objects.create(
            name="Legacy", district="Dhaka", address="Test"
        )
        item = InventoryItem.objects.create(
            warehouse=warehouse,
            item_name="Rice",
            category="DRY_FOOD",
            unit="kg",
            current_quantity=Decimal("12.50"),
        )
        migration = import_module("inventory.migrations.0004_opening_batches")
        migration.opening_balances(apps, SimpleNamespace(connection=connection))
        batch = item.batches.get()
        self.assertEqual(batch.remaining_quantity, Decimal("12.50"))
        self.assertEqual(batch.source, "OPENING")
        self.assertIsNone(batch.donation_item_id)
        item.refresh_from_db()
        self.assertEqual(item.current_quantity, Decimal("12.50"))

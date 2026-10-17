from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from accounts.services import approve_role, request_role
from campaigns.models import DisasterCampaign


class OperationsWebsiteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            "operations_admin", "operations@example.invalid", "Test-password-123"
        )
        cls.user = User.objects.create_user(
            "operations_donor", "operations-donor@example.invalid", "Test-password-123"
        )
        cls.membership = request_role(cls.user, "DONOR")
        approve_role(cls.admin, cls.membership)
        for number in range(3):
            DisasterCampaign.objects.create(
                name=f"Older campaign {number}",
                disaster_type="FLOOD",
                description="Demo",
                district="Sylhet",
                start_date=timezone.localdate(),
                status="ACTIVE",
                created_by=cls.admin,
            )

    def campaign_data(self, name="Operations campaign", status="ACTIVE"):
        return {
            "name": name,
            "disaster_type": "FLOOD",
            "description": "Created through Operations",
            "district": "Sylhet",
            "upazila": "",
            "union_name": "",
            "start_date": str(timezone.localdate()),
            "end_date": "",
            "target_amount": "1000",
            "status": status,
            "_save": "Save",
        }

    def test_operations_add_edit_delete_updates_public_pages_and_donation_choices(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("admin:campaigns_disastercampaign_add"), self.campaign_data()
        )
        self.assertEqual(response.status_code, 302)
        campaign = DisasterCampaign.objects.get(name="Operations campaign")
        self.assertContains(self.client.get(reverse("home")), campaign.name)
        self.assertContains(self.client.get(reverse("campaigns:list")), campaign.name)
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse("donor:goods")), campaign.name)
        self.client.force_login(self.admin)
        self.assertEqual(
            self.client.post(
                reverse("admin:campaigns_disastercampaign_change", args=[campaign.pk]),
                self.campaign_data("Updated campaign"),
            ).status_code,
            302,
        )
        self.assertContains(self.client.get(reverse("home")), "Updated campaign")
        self.assertNotContains(self.client.get(reverse("home")), "Operations campaign")
        response = self.client.post(
            reverse("admin:campaigns_disastercampaign_delete", args=[campaign.pk]),
            {"post": "yes"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(DisasterCampaign.objects.filter(pk=campaign.pk).exists())
        self.assertNotContains(self.client.get(reverse("home")), "Updated campaign")
        self.assertNotContains(
            self.client.get(reverse("campaigns:list")), "Updated campaign"
        )
        self.client.force_login(self.user)
        self.assertNotContains(
            self.client.get(reverse("donor:money")), "Updated campaign"
        )

    def test_draft_publish_and_unpublish_controls_visibility(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("admin:campaigns_disastercampaign_add"),
            self.campaign_data(status="DRAFT"),
            follow=True,
        )
        self.assertContains(response, "This campaign is hidden")
        campaign = DisasterCampaign.objects.get(name="Operations campaign")
        self.assertNotContains(self.client.get(reverse("home")), campaign.name)
        url = reverse("admin:campaigns_disastercampaign_changelist")
        for action, visible in [("publish", True), ("unpublish", False)]:
            response = self.client.post(
                url, {"action": action, "_selected_action": [campaign.pk]}
            )
            self.assertEqual(response.status_code, 302)
            page = self.client.get(reverse("home"))
            if visible:
                self.assertContains(page, campaign.name)
            else:
                self.assertNotContains(page, campaign.name)

    def test_role_deletion_in_operations_removes_access_and_dashboard_segment(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("admin:accounts_userrole_delete", args=[self.membership.pk]),
            {"post": "yes"},
        )
        self.assertEqual(response.status_code, 302)
        self.client.force_login(self.user)
        self.assertNotContains(
            self.client.get(reverse("dashboard:home")), "Donor Segment"
        )
        self.assertEqual(self.client.get(reverse("donor:goods")).status_code, 403)

    def test_removed_dashboard_url_is_review_center(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("management:index"))
        self.assertContains(response, "<h1>Review center</h1>", html=True)
        self.assertNotContains(response, "Admin dashboard")

    def test_new_operations_campaign_defaults_to_published(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("admin:campaigns_disastercampaign_add"))
        self.assertEqual(response.context["adminform"].form["status"].value(), "ACTIVE")
        self.assertContains(
            response, "Choose DRAFT only if you want to keep it hidden."
        )

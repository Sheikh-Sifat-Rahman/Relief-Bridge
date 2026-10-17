from io import BytesIO
from tempfile import TemporaryDirectory

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from accounts.models import User
from accounts.services import approve_role, request_role
from campaigns.models import DisasterCampaign

from .models import DonationItem


class GoodsPhotoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            "photo_admin", "photo-admin@example.invalid", "Test-password-123"
        )
        cls.donor = User.objects.create_user(
            "photo_donor", "photo-donor@example.invalid", "Test-password-123"
        )
        cls.other = User.objects.create_user(
            "other_photo", "other-photo@example.invalid", "Test-password-123"
        )
        approve_role(cls.admin, request_role(cls.donor, "DONOR"))
        cls.campaign = DisasterCampaign.objects.create(
            name="Photo test",
            description="Demo",
            district="Sylhet",
            disaster_type="FLOOD",
            start_date=timezone.localdate(),
            status="ACTIVE",
            created_by=cls.admin,
        )

    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        settings = self.settings(MEDIA_ROOT=temporary.name)
        settings.enable()
        self.addCleanup(settings.disable)
        self.client.force_login(self.donor)

    def image(self, format="PNG", size=(20, 20)):
        output = BytesIO()
        Image.new("RGB", size, "green").save(output, format=format)
        return SimpleUploadedFile(
            "photo." + format.lower(),
            output.getvalue(),
            content_type="image/" + format.lower(),
        )

    def submit(self, photo=None):
        data = {
            "campaign": self.campaign.pk,
            "category": "BLANKET",
            "item_name": "Blanket",
            "quantity": "2",
            "unit": "piece",
            "condition": "New",
        }
        if photo is not None:
            data["photo"] = photo
        return self.client.post(reverse("donor:goods"), data)

    def test_photo_is_optional(self):
        self.assertEqual(self.submit().status_code, 302)
        item = DonationItem.objects.get()
        self.assertFalse(item.photo)
        self.assertEqual(
            self.client.get(reverse("donor:photo", args=[item.pk])).status_code, 404
        )

    def test_upload_is_normalized_and_shown_in_review(self):
        self.assertEqual(self.submit(self.image(size=(2000, 1000))).status_code, 302)
        item = DonationItem.objects.get()
        with item.photo.open("rb") as file:
            image = Image.open(file)
            self.assertEqual(image.format, "JPEG")
            self.assertEqual(image.size, (1600, 800))
            self.assertFalse(image.getexif())
        photo_url = reverse("donor:photo", args=[item.pk])
        response = self.client.get(reverse("donor:detail", args=[item.donation_id]))
        self.assertContains(response, photo_url)
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("management:review", args=["donation", item.donation_id])
        )
        self.assertContains(response, photo_url)
        response = self.client.get(
            reverse("admin:donations_donationitem_change", args=[item.pk])
        )
        self.assertContains(response, photo_url)
        self.assertNotContains(response, 'type="file"')

    def test_photo_access_is_private(self):
        self.submit(self.image())
        item = DonationItem.objects.get()
        url = reverse("donor:photo", args=[item.pk])
        for user in [self.donor, self.admin]:
            self.client.force_login(user)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "image/jpeg")
            self.assertEqual(response["Cache-Control"], "private, no-store")
            response.close()
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_nonimage_is_rejected(self):
        response = self.submit(
            SimpleUploadedFile("fake.jpg", b"not an image", content_type="image/jpeg")
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors.get("photo"))
        self.assertFalse(DonationItem.objects.exists())

    def test_unsupported_format_is_rejected(self):
        response = self.submit(self.image(format="GIF"))
        self.assertContains(response, "Use a JPEG, PNG or WebP photo.")
        self.assertFalse(DonationItem.objects.exists())

    def test_oversized_image_is_rejected(self):
        photo = self.image()
        photo = SimpleUploadedFile(
            "large.png",
            photo.read() + b"x" * (5 * 1024 * 1024),
            content_type="image/png",
        )
        response = self.submit(photo)
        self.assertContains(response, "Choose a photo smaller than 5 MB.")
        self.assertFalse(DonationItem.objects.exists())

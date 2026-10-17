from django import forms

from campaigns.models import DisasterCampaign

from .models import DonationItem


class GoodsDonationForm(forms.ModelForm):
    campaign = forms.ModelChoiceField(
        queryset=DisasterCampaign.objects.filter(status="ACTIVE")
    )

    class Meta:
        model = DonationItem
        fields = [
            "campaign",
            "category",
            "item_name",
            "quantity",
            "unit",
            "condition",
            "expiration_date",
            "photo",
        ]
        widgets = {"expiration_date": forms.DateInput(attrs={"type": "date"})}

    def clean_photo(self):
        from io import BytesIO
        from uuid import uuid4

        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image, ImageOps

        photo = self.cleaned_data.get("photo")
        if not photo:
            return photo
        if photo.size > 5 * 1024 * 1024:
            raise forms.ValidationError("Choose a photo smaller than 5 MB.")
        photo.seek(0)
        try:
            with Image.open(photo) as image:
                if image.format not in {"JPEG", "PNG", "WEBP"}:
                    raise forms.ValidationError("Use a JPEG, PNG or WebP photo.")
                if image.width * image.height > 20_000_000:
                    raise forms.ValidationError(
                        "Choose a photo with no more than 20 megapixels."
                    )
                image = ImageOps.exif_transpose(image).convert("RGB")
                image.thumbnail((1600, 1600))
                output = BytesIO()
                image.save(output, format="JPEG", quality=85)
        except (OSError, ValueError, Image.DecompressionBombError):
            raise forms.ValidationError(
                "This photo could not be read. Choose another image."
            )
        return SimpleUploadedFile(
            f"{uuid4().hex}.jpg", output.getvalue(), content_type="image/jpeg"
        )

    def clean_expiration_date(self):
        from django.utils import timezone

        value = self.cleaned_data["expiration_date"]
        if value and value < timezone.localdate():
            raise forms.ValidationError("Expired goods cannot be donated.")
        return value


class MoneyDonationForm(forms.Form):
    campaign = forms.ModelChoiceField(
        queryset=DisasterCampaign.objects.filter(status="ACTIVE")
    )
    amount = forms.DecimalField(min_value=0.01, max_digits=14, decimal_places=2)

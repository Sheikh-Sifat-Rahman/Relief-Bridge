from django import forms

from campaigns.models import DisasterCampaign

from .models import AidRequest


class AidRequestForm(forms.ModelForm):
    class Meta:
        model = AidRequest
        fields = [
            "campaign",
            "family_members",
            "children_count",
            "elderly_count",
            "house_damage",
            "displaced",
            "income_lost",
            "safe_water_available",
            "requested_items",
            "explanation",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["campaign"].queryset = DisasterCampaign.objects.filter(
            status="ACTIVE"
        )

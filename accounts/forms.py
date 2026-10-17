from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from aidseekers.models import AidSeekerProfile
from volunteers.models import VolunteerProfile

from .models import DonorProfile, User


class RegistrationForm(UserCreationForm):
    roles = forms.MultipleChoiceField(
        choices=[
            ("DONOR", "Donor (approval required)"),
            ("VOLUNTEER", "Volunteer (approval required)"),
            ("AID_SEEKER", "Aid seeker (verification required)"),
        ],
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = User
        fields = [
            "username",
            "email",
            "first_name",
            "last_name",
            "phone",
            "password1",
            "password2",
            "roles",
        ]


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "phone"]


class DonorProfileForm(forms.ModelForm):
    class Meta:
        model = DonorProfile
        fields = ["display_name", "phone", "address"]


class VolunteerProfileForm(forms.ModelForm):
    class Meta:
        model = VolunteerProfile
        fields = []


class SeekerProfileForm(forms.ModelForm):
    class Meta:
        model = AidSeekerProfile
        exclude = ["user", "verification_status"]


class HouseholdForm(SeekerProfileForm):
    """Household completion is available before role activation."""


class AdminLoginForm(AuthenticationForm):
    username = forms.EmailField(
        label="Admin email",
        widget=forms.EmailInput(attrs={"autocomplete": "username", "autofocus": True}),
    )

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not user.is_staff:
            raise forms.ValidationError(
                "Use an administrator account to sign in here.", code="not_staff"
            )


class PublicLoginForm(AuthenticationForm):
    username = forms.CharField(
        label="Username or email",
        widget=forms.TextInput(attrs={"autocomplete": "username", "autofocus": True}),
    )

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if user.is_staff or user.is_superuser:
            raise forms.ValidationError(
                "Administrator accounts must use Log in as administration.",
                code="admin_login_required",
            )

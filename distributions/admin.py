from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path

from audit.services import log

from .models import (
    Distribution,
    DistributionAssignment,
    DistributionEvent,
    DistributionItem,
)
from .services import (
    confirm_distribution,
    duplicate_distributions,
    record_duplicate_warning,
)


class DistributionForm(forms.ModelForm):
    class Meta:
        model = Distribution
        fields = "__all__"

    def clean(self):
        data = super().clean()
        event = data.get("distribution_event")
        aid = data.get("aid_request")
        beneficiary = data.get("beneficiary")
        volunteer = data.get("volunteer")
        if (
            event
            and aid
            and (
                aid.campaign_id != event.campaign_id
                or aid.seeker_id != getattr(beneficiary, "pk", None)
            )
        ):
            raise ValidationError("Request, campaign and beneficiary must match.")
        if (
            event
            and volunteer
            and not DistributionAssignment.objects.filter(
                distribution_event=event, volunteer=volunteer
            ).exists()
        ):
            raise ValidationError("Assign this volunteer to the event first.")
        return data


class ItemInline(admin.TabularInline):
    model = DistributionItem
    extra = 1


class ConfirmForm(forms.Form):
    override_reason = forms.CharField(
        required=False,
        widget=forms.Textarea,
        help_text="Required to override a possible duplicate. Explain why additional assistance is appropriate.",
    )


@admin.register(Distribution)
class DistributionAdmin(admin.ModelAdmin):
    form = DistributionForm
    list_display = [
        "distribution_code",
        "distribution_event",
        "status",
        "duplicate_warning",
    ]
    readonly_fields = [
        "distribution_code",
        "distributed_at",
        "status",
        "duplicate_warning",
        "override_reason",
    ]
    inlines = [ItemInline]
    change_form_template = "management/distribution_change.html"

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.status == "COMPLETED":
            return [f.name for f in Distribution._meta.fields]
        return self.readonly_fields

    def get_inline_instances(self, request, obj=None):
        if obj and obj.status == "COMPLETED":
            return []
        return super().get_inline_instances(request, obj)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        log(
            request.user,
            "Distribution updated" if change else "Distribution creation",
            obj,
        )

    def get_urls(self):
        return [
            path(
                "<int:pk>/confirm/",
                self.admin_site.admin_view(self.confirm),
                name="distribution_confirm",
            )
        ] + super().get_urls()

    def confirm(self, request, pk):
        if not self.has_change_permission(request):
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied
        obj = get_object_or_404(Distribution, pk=pk)
        duplicates = duplicate_distributions(obj)
        form = ConfirmForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            if duplicates.exists():
                record_duplicate_warning(request.user, obj)
            try:
                confirm_distribution(
                    request.user, obj.pk, form.cleaned_data["override_reason"]
                )
                self.message_user(
                    request,
                    "Distribution completed. Inventory and audit ledger updated atomically.",
                )
                return redirect("admin:distributions_distribution_change", obj.pk)
            except ValidationError as error:
                form.add_error(None, error)
        return render(
            request,
            "management/action.html",
            dict(
                self.admin_site.each_context(request),
                form=form,
                title=f"Confirm {obj}",
                duplicates=duplicates,
            ),
        )


@admin.register(DistributionEvent)
class EventAdmin(admin.ModelAdmin):
    readonly_fields = ["created_by", "created_at"]

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
        log(request.user, "Distribution event updated", obj)


admin.site.register(DistributionAssignment)

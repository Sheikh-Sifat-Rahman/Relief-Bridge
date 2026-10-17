from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.utils.html import format_html

from inventory.models import Warehouse

from .models import Donation, DonationItem, MoneyDonation
from .services import inspect_goods


class InspectionForm(forms.Form):
    warehouse = forms.ModelChoiceField(
        queryset=Warehouse.objects.filter(status="ACTIVE")
    )
    accepted = forms.DecimalField(min_value=0, max_digits=14, decimal_places=2)
    reason = forms.CharField(required=False, widget=forms.Textarea)


@admin.register(Donation)
class DonationAdmin(admin.ModelAdmin):
    list_display = ["donation_code", "campaign", "donation_type", "status"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(DonationItem)
class ItemAdmin(admin.ModelAdmin):
    exclude = ["photo"]
    list_display = ["donation", "item_name", "quantity", "inspection_status"]
    readonly_fields = [
        f.name for f in DonationItem._meta.fields if f.name != "photo"
    ] + ["photo_preview"]

    @admin.display(description="Goods photo")
    def photo_preview(self, obj):
        if not obj.photo:
            return "No photo attached."
        url = reverse("donor:photo", args=[obj.pk])
        return format_html(
            '<a href="{}" target="_blank" rel="noopener"><img src="{}" alt="Goods photo" style="max-width:360px;max-height:300px;object-fit:contain"></a>',
            url,
            url,
        )

    change_form_template = "management/inspection_change.html"

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_urls(self):
        return [
            path(
                "<int:pk>/inspect/",
                self.admin_site.admin_view(self.inspect),
                name="donation_inspect",
            )
        ] + super().get_urls()

    def inspect(self, request, pk):
        if not self.has_change_permission(request):
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied
        item = get_object_or_404(DonationItem, pk=pk)
        form = InspectionForm(request.POST or None, initial={"accepted": item.quantity})
        if request.method == "POST" and form.is_valid():
            try:
                inspect_goods(
                    request.user,
                    item.pk,
                    form.cleaned_data["warehouse"],
                    form.cleaned_data["accepted"],
                    form.cleaned_data["reason"],
                )
                self.message_user(
                    request, "Inspection recorded; accepted goods added to inventory."
                )
                return redirect("admin:donations_donationitem_change", item.pk)
            except ValidationError as error:
                form.add_error(None, error)
        return render(
            request,
            "management/action.html",
            dict(
                self.admin_site.each_context(request),
                form=form,
                title=f"Inspect {item.item_name}",
            ),
        )


@admin.register(MoneyDonation)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ["donation", "amount", "transaction_reference", "payment_status"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

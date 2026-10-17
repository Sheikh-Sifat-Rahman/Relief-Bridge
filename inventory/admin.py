from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path

from .models import InventoryBatch, InventoryItem, InventoryTransaction, Warehouse
from .services import move_stock


class MovementForm(forms.Form):
    transaction_type = forms.ChoiceField(
        choices=[
            ("STOCK_IN", "Stock in"),
            ("STOCK_OUT", "Stock out"),
            ("ADJUSTMENT", "Signed adjustment"),
        ]
    )
    quantity = forms.DecimalField(max_digits=14, decimal_places=2)
    source_reference = forms.CharField(max_length=100)
    notes = forms.CharField(widget=forms.Textarea)


@admin.register(InventoryItem)
class InventoryAdmin(admin.ModelAdmin):
    list_display = [
        "item_name",
        "warehouse",
        "category",
        "current_quantity",
        "reserved_quantity",
        "available_quantity",
        "unit",
    ]
    readonly_fields = [
        "current_quantity",
        "reserved_quantity",
        "available_quantity",
        "updated_at",
    ]
    change_form_template = "management/inventory_change.html"

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.batches.exists():
            return [*self.readonly_fields, "warehouse", "category", "item_name", "unit"]
        return self.readonly_fields

    def get_urls(self):
        return [
            path(
                "<int:pk>/movement/",
                self.admin_site.admin_view(self.movement),
                name="inventory_movement",
            )
        ] + super().get_urls()

    def movement(self, request, pk):
        if not self.has_change_permission(request):
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied
        item = get_object_or_404(InventoryItem, pk=pk)
        form = MovementForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            try:
                move_stock(
                    item.pk,
                    form.cleaned_data["quantity"],
                    form.cleaned_data["transaction_type"],
                    request.user,
                    "MANUAL",
                    form.cleaned_data["source_reference"],
                    form.cleaned_data["notes"],
                )
                self.message_user(request, "Stock movement recorded.")
                return redirect("admin:inventory_inventoryitem_change", item.pk)
            except ValidationError as error:
                form.add_error(None, error)
        return render(
            request,
            "management/action.html",
            dict(
                self.admin_site.each_context(request),
                form=form,
                title=f"Record movement: {item}",
            ),
        )


@admin.register(InventoryTransaction)
class MovementAdmin(admin.ModelAdmin):
    list_display = [
        "created_at",
        "inventory_item",
        "transaction_type",
        "quantity",
        "performed_by",
        "source_reference",
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(Warehouse)


@admin.register(InventoryBatch)
class BatchAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "inventory_item",
        "origin",
        "received",
        "remaining",
        "reserved",
        "expires",
    ]
    list_filter = ["source", "inventory_item__warehouse"]
    search_fields = [
        "inventory_item__item_name",
        "donation_item__donation__donation_code",
    ]
    list_select_related = ["inventory_item__warehouse", "donation_item__donation"]

    @admin.display(description="Origin")
    def origin(self, obj):
        return (
            obj.donation_item.donation.donation_code
            if obj.donation_item_id
            else obj.get_source_display()
        )

    @admin.display(description="Received")
    def received(self, obj):
        return f"{obj.received_quantity} {obj.inventory_item.unit}"

    @admin.display(description="Remaining")
    def remaining(self, obj):
        return f"{obj.remaining_quantity} {obj.inventory_item.unit}"

    @admin.display(description="Reserved")
    def reserved(self, obj):
        return f"{obj.reserved_quantity} {obj.inventory_item.unit}"

    @admin.display(description="Expires", ordering="expiration_date")
    def expires(self, obj):
        return obj.expiration_date

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

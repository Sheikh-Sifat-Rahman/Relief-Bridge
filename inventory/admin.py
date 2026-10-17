from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path

from .models import InventoryItem, InventoryTransaction, Warehouse
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
    list_display = ["item_name", "warehouse", "category", "current_quantity", "unit"]
    readonly_fields = ["current_quantity", "updated_at"]
    change_form_template = "management/inventory_change.html"

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

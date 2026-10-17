from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from audit.services import log

from .models import DonorProfile, Role, User, UserRole
from .services import approve_role


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("Contact", {"fields": ["phone"]}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("Contact", {"fields": ["email"]}),)


@admin.register(UserRole)
class UserRoleAdmin(admin.ModelAdmin):
    list_display = ["user", "role", "status", "approved_at"]
    list_filter = ["status", "role"]
    readonly_fields = ["created_at", "approved_at"]
    actions = ["activate"]

    @admin.action(description="Approve selected roles")
    def activate(self, request, queryset):
        for membership in queryset:
            approve_role(request.user, membership)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if obj.status == "ACTIVE":
            approve_role(request.user, obj)
        else:
            log(request.user, "Role status updated", obj, obj.status)


admin.site.register(Role)
admin.site.register(DonorProfile)

from django.contrib import admin, messages

from audit.services import log

from .models import DisasterCampaign


@admin.register(DisasterCampaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = ["name", "district", "disaster_type", "status", "collected_amount"]
    list_filter = ["status", "disaster_type", "district"]
    actions = ["publish", "unpublish"]
    readonly_fields = ["collected_amount", "created_by", "created_at", "updated_at"]

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        initial.setdefault("status", "ACTIVE")
        return initial

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        field = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name == "status" and field is not None:
            field.help_text = "ACTIVE publishes the campaign on the website and in donation choices. Choose DRAFT only if you want to keep it hidden."
        return field

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
        log(request.user, "Campaign updated" if change else "Campaign creation", obj)

    @admin.action(description="Publish selected campaigns on the website")
    def publish(self, request, queryset):
        for campaign in queryset:
            campaign.status = "ACTIVE"
            campaign.save(update_fields=["status", "updated_at"])
            log(request.user, "Campaign published", campaign)
        self.message_user(request, "Selected campaigns are now visible on the website.")

    @admin.action(description="Unpublish selected campaigns from the website")
    def unpublish(self, request, queryset):
        for campaign in queryset:
            campaign.status = "CLOSED"
            campaign.save(update_fields=["status", "updated_at"])
            log(request.user, "Campaign unpublished", campaign)
        self.message_user(
            request,
            "Selected campaigns were removed from public pages. Existing records are preserved.",
        )

    def response_add(self, request, obj, post_url_continue=None):
        self.visibility_message(request, obj)
        return super().response_add(request, obj, post_url_continue)

    def response_change(self, request, obj):
        self.visibility_message(request, obj)
        return super().response_change(request, obj)

    def visibility_message(self, request, obj):
        if obj.status == "ACTIVE":
            self.message_user(
                request,
                "This campaign is published. It appears in Campaigns and donation/request forms; the three newest active campaigns appear on the homepage.",
                messages.INFO,
            )
        else:
            self.message_user(
                request,
                "This campaign is hidden from public pages and donation/request forms. Set status to ACTIVE or use Publish to display it.",
                messages.WARNING,
            )

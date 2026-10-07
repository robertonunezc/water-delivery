from django.contrib import admin
from unfold.admin import ModelAdmin

from core.admin_mixins import SoftDeleteAdminMixin

from .models import Reminder


@admin.register(Reminder)
class ReminderAdmin(SoftDeleteAdminMixin, ModelAdmin):
    list_display = (
        "title",
        "client",
        "created_by",
        "reminder_date",
        "urgent",
        "completed_at",
        "completed_by",
        "deleted_at",
    )
    list_filter = (
        "urgent",
        "completed_at",
        "reminder_date",
        "created_by",
        "client",
        "deleted_at",
    )
    search_fields = (
        "title",
        "description",
        "client__name",
        "created_by__username",
        "created_by__first_name",
        "created_by__last_name",
    )
    autocomplete_fields = ("client", "created_by", "completed_by")
    readonly_fields = ("created_at", "updated_at", "deleted_at", "completed_at", "completed_by")
    date_hierarchy = "reminder_date"
    ordering = ("-urgent", "reminder_date", "-created_at")

    fieldsets = (
        ("Recordatorio", {
            "fields": (
                "title",
                "description",
                ("client", "reminder_date"),
                "urgent",
                "created_by",
            )
        }),
        ("Estado", {
            "fields": ("completed_at", "completed_by", "deleted_at"),
        }),
        ("Sistema", {
            "fields": (("created_at", "updated_at"),),
            "classes": ("collapse",),
        }),
    )

    def get_queryset(self, request):
        return self.model.all_objects.select_related(
            "client",
            "created_by",
            "completed_by",
        )

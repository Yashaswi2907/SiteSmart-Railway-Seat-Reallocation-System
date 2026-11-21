from django.contrib import admin

from .models import ActivityLog, TrainSimulation


@admin.register(TrainSimulation)
class TrainSimulationAdmin(admin.ModelAdmin):
    list_display = ("train", "journey_date", "status", "current_index", "is_paused", "auto_advance")
    list_filter = ("status",)


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "category", "action", "actor", "description")
    list_filter = ("category", "action")
    search_fields = ("description",)
    readonly_fields = [f.name for f in ActivityLog._meta.fields]

    def has_add_permission(self, request):
        return False

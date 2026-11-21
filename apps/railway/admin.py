from django.contrib import admin

from .models import Coach, Seat, Station, Train, TrainRoute, TrainStop


@admin.register(Station)
class StationAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "city", "state", "zone", "is_active")
    list_filter = ("zone", "is_active", "state")
    search_fields = ("code", "name", "city")


class TrainStopInline(admin.TabularInline):
    model = TrainStop
    extra = 0
    ordering = ("sequence",)
    autocomplete_fields = ("station",)


@admin.register(TrainRoute)
class TrainRouteAdmin(admin.ModelAdmin):
    list_display = ("train", "name")
    inlines = [TrainStopInline]


class CoachInline(admin.TabularInline):
    model = Coach
    extra = 0


@admin.register(Train)
class TrainAdmin(admin.ModelAdmin):
    list_display = ("number", "name", "train_type", "running_days", "is_active")
    list_filter = ("train_type", "is_active")
    search_fields = ("number", "name")
    inlines = [CoachInline]


@admin.register(Coach)
class CoachAdmin(admin.ModelAdmin):
    list_display = ("coach_number", "train", "coach_class", "position", "is_active")
    list_filter = ("coach_class", "train")


@admin.register(Seat)
class SeatAdmin(admin.ModelAdmin):
    list_display = ("seat_number", "coach", "berth_type", "is_active")
    list_filter = ("coach__train", "coach__coach_class", "berth_type", "is_active")
    list_select_related = ("coach__train",)

from django.contrib import admin

from .models import BoardingStatus, Booking, Cancellation, Passenger, SeatAllocation


class PassengerInline(admin.TabularInline):
    model = Passenger
    extra = 0
    raw_id_fields = ("seat",)


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ("pnr", "train", "journey_date", "from_stop", "to_stop", "coach_class", "status", "user")
    list_filter = ("status", "coach_class", "is_reallocated", "journey_date")
    search_fields = ("pnr", "user__username", "passengers__name")
    date_hierarchy = "journey_date"
    inlines = [PassengerInline]
    raw_id_fields = ("user", "from_stop", "to_stop")


@admin.register(BoardingStatus)
class BoardingStatusAdmin(admin.ModelAdmin):
    list_display = ("passenger", "status", "verified_by", "verified_at")
    list_filter = ("status",)


@admin.register(SeatAllocation)
class SeatAllocationAdmin(admin.ModelAdmin):
    list_display = ("seat", "journey_date", "segment_index", "status", "passenger")
    list_filter = ("status", "journey_date")
    raw_id_fields = ("passenger", "seat")


@admin.register(Cancellation)
class CancellationAdmin(admin.ModelAdmin):
    list_display = ("booking", "cancelled_by", "refund_amount", "segments_released", "created_at")

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import PassengerProfile, TTProfile, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "email", "first_name", "last_name", "role", "is_active", "date_joined")
    list_filter = ("role", "is_active", "is_staff")
    search_fields = ("username", "email", "first_name", "last_name")
    fieldsets = BaseUserAdmin.fieldsets + (("SiteSmart", {"fields": ("role", "phone")}),)
    add_fieldsets = BaseUserAdmin.add_fieldsets + (("SiteSmart", {"fields": ("email", "role", "phone")}),)


@admin.register(PassengerProfile)
class PassengerProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "gender", "city", "preferred_class")
    search_fields = ("user__username", "user__email", "city")


@admin.register(TTProfile)
class TTProfileAdmin(admin.ModelAdmin):
    list_display = ("employee_id", "user", "designation", "division", "is_on_duty")
    list_filter = ("designation", "is_on_duty")
    filter_horizontal = ("assigned_trains",)
    search_fields = ("employee_id", "user__username", "user__first_name")

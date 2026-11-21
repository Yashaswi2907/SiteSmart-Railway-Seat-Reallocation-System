from rest_framework.permissions import BasePermission


class IsPassenger(BasePermission):
    message = "Only passenger accounts can make bookings."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_passenger)


class IsTTOrAdmin(BasePermission):
    message = "This action is limited to TT/TTE staff and administrators."

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and (u.is_tt or u.is_portal_admin))


class IsPortalAdmin(BasePermission):
    message = "Administrator access is required."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_portal_admin)

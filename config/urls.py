"""Root URL configuration."""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "SiteSmart Rail — Django Administration"
admin.site.site_title = "SiteSmart Rail Admin"
admin.site.index_title = "Data administration"

urlpatterns = [
    path("", include("apps.core.urls")),
    path("accounts/", include("apps.accounts.urls")),
    path("", include("apps.railway.urls")),
    path("", include("apps.bookings.urls")),
    path("tt/", include("apps.operations.urls")),
    path("manage/", include("apps.adminpanel.urls")),
    path("api/", include("apps.api.urls")),
    path("django-admin/", admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

handler403 = "apps.core.views.error_403"
handler404 = "apps.core.views.error_404"
handler500 = "apps.core.views.error_500"

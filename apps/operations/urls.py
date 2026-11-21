from django.urls import path

from . import views

app_name = "operations"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("run/<int:train_id>/<str:date>/", views.run_console, name="run_console"),
    path("lookup/", views.lookup, name="lookup"),
]

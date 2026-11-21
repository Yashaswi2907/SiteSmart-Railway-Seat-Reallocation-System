from django.urls import path

from . import views

app_name = "adminpanel"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    # Network
    path("trains/", views.train_list, name="train_list"),
    path("trains/add/", views.train_create, name="train_create"),
    path("trains/<int:pk>/", views.train_detail, name="train_detail"),
    path("trains/<int:pk>/edit/", views.train_edit, name="train_edit"),
    path("trains/<int:pk>/delete/", views.train_delete, name="train_delete"),
    path("trains/<int:pk>/stops/add/", views.stop_add, name="stop_add"),
    path("stops/<int:pk>/edit/", views.stop_edit, name="stop_edit"),
    path("stops/<int:pk>/delete/", views.stop_delete, name="stop_delete"),
    path("stops/<int:pk>/move/<str:direction>/", views.stop_move, name="stop_move"),
    path("trains/<int:pk>/coaches/add/", views.coach_add, name="coach_add"),
    path("coaches/<int:pk>/edit/", views.coach_edit, name="coach_edit"),
    path("coaches/<int:pk>/delete/", views.coach_delete, name="coach_delete"),
    path("coaches/<int:pk>/seats/", views.coach_seats, name="coach_seats"),
    path("seats/<int:pk>/toggle/", views.seat_toggle, name="seat_toggle"),
    path("seats/<int:pk>/delete/", views.seat_delete, name="seat_delete"),
    path("stations/", views.station_list, name="station_list"),
    path("stations/add/", views.station_form, name="station_create"),
    path("stations/<int:pk>/edit/", views.station_form, name="station_edit"),
    path("stations/<int:pk>/delete/", views.station_delete, name="station_delete"),
    path("schedules/", views.schedules, name="schedules"),
    # Operations
    path("simulation/", views.simulation, name="simulation"),
    path("allocation/", views.allocation, name="allocation"),
    path("released/", views.released, name="released"),
    path("boarding/", views.boarding_monitor, name="boarding"),
    # Bookings
    path("bookings/", views.booking_list, name="booking_list"),
    path("cancellations/", views.cancellations, name="cancellations"),
    # People
    path("passengers/", views.passenger_list, name="passenger_list"),
    path("users/<int:pk>/toggle/", views.user_toggle, name="user_toggle"),
    path("staff/", views.staff_list, name="staff_list"),
    path("staff/add/", views.staff_form, name="staff_create"),
    path("staff/<int:pk>/edit/", views.staff_form, name="staff_edit"),
    # System
    path("activity/", views.activity, name="activity"),
]

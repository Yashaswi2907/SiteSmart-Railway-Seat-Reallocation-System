from django.urls import path

from . import views

app_name = "bookings"

urlpatterns = [
    path("passenger/", views.passenger_dashboard, name="passenger_dashboard"),
    path("passenger/bookings/", views.my_bookings, name="my_bookings"),
    path("passenger/bookings/<str:pnr>/", views.booking_detail, name="booking_detail"),
    path("passenger/bookings/<str:pnr>/ticket/", views.ticket, name="ticket"),
    path("passenger/bookings/<str:pnr>/ticket.pdf", views.ticket_pdf, name="ticket_pdf"),
    path("passenger/bookings/<str:pnr>/qr.png", views.ticket_qr, name="ticket_qr"),
    path("book/<int:train_id>/", views.book, name="book"),
    path("pnr-status/", views.pnr_status, name="pnr_status"),
    path("tickets/verify/<str:pnr>/<str:signature>/", views.verify_ticket, name="verify_ticket"),
]

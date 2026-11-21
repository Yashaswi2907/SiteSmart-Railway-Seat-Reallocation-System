from django.urls import path

from .views import admin, booking, operations, public

app_name = "api"

urlpatterns = [
    # Public
    path("stations/", public.StationListView.as_view(), name="stations"),
    path("trains/search/", public.TrainSearchView.as_view(), name="train_search"),
    path("pnr/<str:pnr>/", public.PNRStatusView.as_view(), name="pnr_status"),
    # Passenger booking
    path("trains/<int:train_id>/coaches/", booking.CoachAvailabilityView.as_view(), name="coaches"),
    path("trains/<int:train_id>/seat-map/", booking.SeatMapView.as_view(), name="seat_map"),
    path("trains/<int:train_id>/suggest-seats/", booking.SuggestSeatsView.as_view(), name="suggest_seats"),
    path("bookings/", booking.BookingListCreateView.as_view(), name="bookings"),
    path("bookings/<str:pnr>/cancel/", booking.BookingCancelView.as_view(), name="booking_cancel"),
    # Train runs (simulation) and TT operations
    path("runs/<int:train_id>/<str:date>/position/", operations.RunPositionView.as_view(), name="run_position"),
    path("runs/<int:train_id>/<str:date>/", operations.RunConsoleView.as_view(), name="run_console"),
    path("runs/<int:train_id>/<str:date>/control/", operations.RunControlView.as_view(), name="run_control"),
    path("runs/<int:train_id>/<str:date>/passengers/", operations.RunPassengersView.as_view(), name="run_passengers"),
    path("runs/<int:train_id>/<str:date>/occupancy/", operations.RunOccupancyView.as_view(), name="run_occupancy"),
    path("runs/<int:train_id>/<str:date>/released/", operations.RunReleasedView.as_view(), name="run_released"),
    path("passengers/<int:passenger_id>/verify/", operations.VerifyPassengerView.as_view(), name="verify_passenger"),
    path("tt/pnr/<str:pnr>/", operations.TTPnrLookupView.as_view(), name="tt_pnr"),
    # Administration
    path("admin/stats/", admin.AdminStatsView.as_view(), name="admin_stats"),
    path("admin/allocation-check/", admin.AllocationCheckView.as_view(), name="allocation_check"),
    path("admin/seat-matrix/", admin.SeatMatrixView.as_view(), name="seat_matrix"),
]

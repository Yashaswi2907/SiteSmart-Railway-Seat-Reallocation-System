# Testing

```bash
python manage.py test                     # everything
python manage.py test apps.bookings -v 2  # allocation engine, verbose
```

The test database is a file (`test_db.sqlite3`, created and removed automatically) so the
concurrency tests can open real parallel connections.

| Required area | Where it is tested |
|---------------|--------------------|
| 1. User registration | `apps/accounts/tests/test_auth.py` — success, validation, no role escalation |
| 2. Login and logout | `test_auth.py` — username/e-mail login, wrong password, inactive user, POST-only logout, CSRF |
| 3. Role permissions | `apps/core/tests/test_pages.py::test_role_isolation`, admin `test_non_admin_cannot_post` |
| 4. Train search | `test_pages.py::test_public_pages`, `apps/api/tests/test_api.py::PublicApiTests` |
| 5. Booking creation | `test_engine.py::ReservationTests`, `test_api.py::test_booking_flow_creates_pnr_and_allocations` |
| 6. PNR generation | `test_booking_creates_one_allocation_per_segment`, API booking flow (10-digit, unique) |
| 7. Seat allocation | per-segment rows, best-fit selection, class availability counts |
| 8. Non-overlapping bookings | `test_spec_non_overlapping_bookings_share_a_seat`, exhaustive pair test |
| 9. Overlapping rejection | `test_spec_overlapping_bookings_rejected`, exhaustive 10 × 10 pair test, API 409 |
| 10. TT boarding verification | `NoShowReallocationTests`, `TTApiTests` |
| 11. No-show seat release | `test_complete_specification_scenario`, `test_released_seats_report_lists_eligible_ranges` |
| 12. Train movement | `apps/operations/tests/test_simulation.py`, `test_departed_segments_never_reopen` |
| 13. Cancellation | `CancellationTests`, `test_cancel_own_booking_only` |
| 14. PDF ticket generation | `test_pages.py::test_booking_owner_pages` (content type and `%PDF` header), `test_pdf_ticket_contents` |
| 15. Unauthorised access | role isolation pages, other passenger → 404, unassigned TT → 403, anonymous API refused |

**Reallocation engine combinations**

- every pair of the 10 possible journeys on `A→B→C→D→E` (100 combinations) is booked on
  one seat; the second booking must succeed **iff** the intervals do not overlap
- the overlap function is compared with brute-force set intersection on a 6-stop route
- late no-show after the train left B: only C onwards becomes sellable
- partial no-show in a group booking releases only that passenger's berth
- a simulated "race lost" (availability check bypassed) is caught by the database constraint
- **8 real threads** booking the same berth simultaneously → exactly one booking; mixed
  overlapping concurrent journeys never sell a segment twice

**Manual / browser checks performed before delivery**

Full no-show scenario, booking wizard, cancellation, registration, TT console,
allocation checker, admin CRUD and mobile layouts were exercised in headless Chrome with
no JavaScript console errors.

# REST API reference

Built with Django REST Framework. All endpoints live under `/api/`, return JSON, and use
**session authentication** (sign in through the website first). Every `POST` needs the
`X-CSRFToken` header — the bundled `static/js/app.js` (`SS.api`) adds it automatically.
In debug mode the endpoints are browsable in the browser.

Errors always use one envelope:

```json
{ "error": { "code": "seat_unavailable", "message": "Seat S1/25 is no longer free …", "details": {} } }
```

| HTTP | Typical codes |
|------|---------------|
| 400 | `validation_error`, `invalid_journey`, `wrong_direction`, `not_running`, `past_date` |
| 403 | `permission_denied`, `not_authenticated` |
| 404 | `not_found` |
| 409 | `seat_unavailable`, `race_lost`, `insufficient_seats`, `segment_departed`, `boarding_not_allowed`, `cancellation_not_allowed`, `simulation_error` |

Journey parameters used by several endpoints: `from` and `to` (station codes) and
`date` (`YYYY-MM-DD`, the run date).

## Public

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/stations/?q=kan` | Station autocomplete (code, name, city, state) |
| GET | `/api/trains/search/?from=CNB&to=LKO&date=…&class=SL&passengers=1` | Trains with per-class `total`, `available`, `reallocated`, `fare`, `bookable`, plus `departed` flag |
| GET | `/api/pnr/<pnr>/` | PNR status — seats and boarding, **no passenger names** |

## Passenger (signed-in)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/trains/<id>/coaches/?from&to&date&class` | Coaches with free / released seat counts and fares |
| GET | `/api/trains/<id>/seat-map/?from&to&date&coach=<id>` | Every seat with `state`: `available` \| `reallocated` \| `booked` (+ `occupied_on` segments) |
| GET | `/api/trains/<id>/suggest-seats/?from&to&date&class&count&prefs=LB,UB` | Best-fit seat choice |
| GET | `/api/bookings/` | Own bookings with journey state (passenger role) |
| POST | `/api/bookings/` | Create a booking (passenger role) |
| POST | `/api/bookings/<pnr>/cancel/` | Cancel (owner or admin) — `{"reason": "…"}` |

`POST /api/bookings/` body:

```json
{
  "train_id": 1, "journey_date": "2026-11-21", "from_code": "CNB", "to_code": "LKO",
  "coach_class": "SL",
  "seat_ids": [25],
  "passengers": [{"name": "Ananya Iyer", "age": 27, "gender": "F", "berth_preference": "LB"}],
  "contact_email": "ananya@sitesmart.demo", "contact_phone": "9876543210"
}
```

Omit `seat_ids` to let the server pick seats (best fit). Response `201`:
`{"pnr", "total_fare", "is_reallocated", "seats", "redirect_url"}`.

## Train runs and TT operations (TT assigned to the train, or admin)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/runs/<train_id>/<date>/position/` | Simulated position (any signed-in user) |
| GET | `/api/runs/<train_id>/<date>/` | Console snapshot: simulation, stats, coaches |
| POST | `/api/runs/<train_id>/<date>/control/` | `{"action": "start" \| "pause" \| "resume" \| "step" \| "next_station" \| "auto_on" \| "auto_off", "interval": 20}` |
| GET | `/api/runs/<train_id>/<date>/passengers/?coach&status&q&scope=here\|onboard` | Passenger list with `can_verify` and reason |
| GET | `/api/runs/<train_id>/<date>/occupancy/?coach&segment` | Seat states on one segment |
| GET | `/api/runs/<train_id>/<date>/released/` | Released seats, no-show details, eligible journeys, timeline |
| POST | `/api/passengers/<id>/verify/` | `{"status": "BOARDED" \| "NOT_BOARDED", "remarks": "…"}` |
| GET | `/api/tt/pnr/<pnr>/` | Full booking lookup for TT |

## Administrator

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/stats/` | Dashboard totals and chart series |
| GET | `/api/admin/allocation-check/?train&date&seat&from&to` | What-if check: verdict, conflicts, seat timeline |
| GET | `/api/admin/seat-matrix/?train&date&coach` | Seat × segment occupancy grid |

## Example (curl with a session)

```bash
# public search
curl "http://127.0.0.1:8000/api/trains/search/?from=CNB&to=LKO&date=$(date +%F)&class=SL"
```

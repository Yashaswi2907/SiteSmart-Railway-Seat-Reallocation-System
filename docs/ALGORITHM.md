# The segment-based seat reallocation algorithm

This document explains how SiteSmart Rail decides whether a seat can be sold, how a
no-show's seat is released, and why a seat can never be double-booked. Code references
point to `apps/bookings/services/` and `apps/operations/services/`.

## 1. Vocabulary

| Term | Meaning |
|------|---------|
| **Stop index** | Position of a station on a train's route, `0 … n-1` (`TrainStop.sequence`). |
| **Segment *i*** | The stretch of track from stop *i* to stop *i + 1*. A route with *n* stops has *n − 1* segments. |
| **Journey `s → d`** | Occupies the half-open interval **`[s, d)`** = segments `s, s+1, …, d−1`. |
| **Run** | One train on one `journey_date` (the date it leaves its origin). |
| **Allocation row** | One `SeatAllocation` row = one seat × one run date × one segment. |

Example route `A(0) → B(1) → C(2) → D(3) → E(4)`:

```
stop:      A ─────── B ─────── C ─────── D ─────── E
segment:       0         1         2         3
A→E occupies [0,4) = {0,1,2,3}
B→C occupies [1,2) = {1}
C→D occupies [2,3) = {2}
```

## 2. When do two journeys conflict?

Two journeys on the same seat conflict exactly when their intervals intersect:

```
[s1, d1) ∩ [s2, d2) ≠ ∅   ⇔   s1 < d2  and  s2 < d1
```

(`segments.segments_overlap`). Because intervals are half-open, journeys that merely
*touch* at a station do not conflict — one passenger alights at C as the next boards.

| Journeys | Intervals | Conflict? |
|----------|-----------|-----------|
| B→C and C→D | [1,2) and [2,3) | No — they touch at C |
| B→D and C→E | [1,3) and [2,4) | **Yes** — both need segment 2 (C→D) |
| A→E and anything | [0,4) | **Yes** |
| A→B and D→E | [0,1) and [3,4) | No |

The test suite verifies this rule against brute-force set intersection for every pair
of journeys on 5- and 6-stop routes.

## 3. Data representation

Instead of storing "seat 25 is booked A→E", the engine stores one `SeatAllocation` row
per segment:

| seat | journey_date | segment_index | passenger | status |
|------|--------------|---------------|-----------|--------|
| S1/25 | 2026-11-21 | 0 | Rahul | ACTIVE |
| S1/25 | 2026-11-21 | 1 | Rahul | ACTIVE |
| S1/25 | 2026-11-21 | 2 | Rahul | ACTIVE |

With this shape, "is the seat free for `[s, d)`?" becomes a single indexed query —
*does any ACTIVE row exist with `s ≤ segment_index < d`?* — and the database can enforce
correctness on its own:

```python
UniqueConstraint(fields=["seat", "journey_date", "segment_index"],
                 condition=Q(status="ACTIVE"), name="uniq_active_seat_segment")
```

This **partial unique index** allows any number of RELEASED or CANCELLED rows (history)
but at most one ACTIVE occupant per seat, date and segment.

## 4. Train position

Each run has a `TrainSimulation` row with a state machine:

```
SCHEDULED ─start─▶ AT_STATION(0) ─depart─▶ IN_TRANSIT(0) ─arrive─▶ AT_STATION(1) … AT_STATION(n-1) ─finish─▶ COMPLETED
```

From it the engine derives the **minimum boardable index** — the earliest stop a *new*
journey may start from:

| State | `min_boardable_index` | Why |
|-------|-----------------------|-----|
| SCHEDULED | 0 | Train has not left |
| AT_STATION(k) | k | Passengers can still board at the current halt |
| IN_TRANSIT(k) | k + 1 | The train has left k; the next chance to board is k + 1 |
| COMPLETED | n | Nothing can be booked |

A journey `s → d` is rejected with `TrainDepartedError` when `s < min_boardable_index`.
This is what guarantees that **departed segments are never made available again**: even
if a no-show left segment 0 empty, once the train has left stop 0 nobody can buy a
journey that starts there.

## 5. Availability check

`availability.check_seat_availability(seat, date, s, d)` returns a `SeatCheck` with:

1. `available = False` if the seat or its coach is out of service;
2. the list of ACTIVE rows in `[s, d)` (with PNR and segment names) — any row means a conflict.

`build_journey_context()` adds the schedule and position rules (route order, running day,
date window, `min_boardable_index`). `get_available_seats()` and `class_availability()`
run the same logic in bulk with one query per train.

## 6. Reserving seats (concurrency-safe)

`reservation.reserve_seats()`:

1. Validate passenger data server-side and run a quick pre-check (fast feedback).
2. Open `transaction.atomic()`. SQLite is configured with `transaction_mode = IMMEDIATE`,
   so the write lock is taken **at the start** of the block — two booking requests can
   no longer interleave *check* and *insert*.
3. Rebuild the journey context **inside** the transaction (the train may have moved).
4. Lock the chosen seats with `select_for_update()` (no-op on SQLite, row locks on PostgreSQL).
5. **Re-check occupancy** of every requested segment for every chosen seat.
6. Write `Booking`, `Passenger`, `BoardingStatus` and the per-segment `SeatAllocation` rows.
7. If anything raced past step 5, inserting the allocation rows violates the partial
   unique index → `IntegrityError` → the whole booking is rolled back and the user gets
   *"One of the selected seats was booked by another passenger a moment ago."*

A multi-threaded test fires eight simultaneous requests for the same berth and asserts
exactly one booking is created.

## 7. Processing a no-show

`boarding.process_no_show(passenger, tt_user)`:

1. Lock the passenger and boarding rows.
2. Authorisation: the user must be an administrator or a TT **assigned to this train**.
3. Eligibility (`verification_eligibility`):
   - booking and passenger are confirmed;
   - boarding status is still **PENDING** (a *Boarded* passenger can never be released);
   - the run has started and the train **has reached** the passenger's boarding station;
   - the train has not yet reached the passenger's destination.
4. Set status `NOT_BOARDED`, recording the TT, time and station.
5. `release.release_seat_segments(passenger)` flips the ACTIVE rows to `RELEASED`.
6. Log the no-show and the release; report which segments are now sellable
   (those at or after `min_boardable_index`).

From this moment the seat is free for the released segments, so searches and seat maps
show it as available (and highlight it as *released by a no-show*).

## 8. Choosing a seat — best fit

When a passenger presses *Auto-pick*, `find_eligible_seats()` ranks every free seat by
its **waste**: how many free segments the booking would leave stranded next to it.

```
seat occupied A→B and C→E, request B→C  → gap is exactly [1,2) → waste 0  ← chosen first
completely empty seat, request B→C     → leaves [0,1) and [2,4) free → waste 3
```

Filling tight gaps first (typically the fragments released by no-shows) keeps long free
runs on other seats available for long journeys, which maximises the number of
passengers a train can carry. Groups are kept in one coach where possible and berth
preferences are honoured when a matching seat exists.

## 9. Cancellation

`cancellation.cancel_booking()` (owner or admin only) is allowed while the train has not
departed the boarding station and no passenger on the ticket has been verified. All
ACTIVE rows become `CANCELLED`, so the segments are immediately bookable again, and a
`Cancellation` record stores the simulated charge and refund.

## 10. Worked example (the demo)

Route `NDLS(0) → CNB(1) → LKO(2) → BSB(3)`, seat S1/25, today's run.

| Step | Action | Seat S1/25 segments 0 / 1 / 2 |
|------|--------|-------------------------------|
| 1 | Rahul books NDLS→BSB | A / A / A |
| 2 | TT starts run (min boardable = 0) and marks Rahul *Did not board* | R / R / R |
| 3 | Ananya books CNB→LKO `[1,2)` | R / **A** / R |
| 4 | Rohan books LKO→BSB `[2,3)` | R / A / **A** |
| 5 | Anyone tries CNB→BSB `[1,3)` | rejected: segments 1 and 2 ACTIVE |
| 6 | Train departs NDLS (min boardable = 1) | segment 0 can never be sold again |

`A` = ACTIVE, `R` = RELEASED.

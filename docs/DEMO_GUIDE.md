# Presentation script — no-show reallocation (≈ 8 minutes)

**Before the session**

```bash
python manage.py seed_demo --reset   # makes today's run the demo run
python manage.py runserver
```

Open two browser windows: a normal one and a private/incognito one (separate sessions).
Password for all demo accounts: `Demo@12345` (or your `DEMO_PASSWORD`).

| # | Who | Do | Say |
|---|-----|----|-----|
| 1 | Anyone | Home page → scroll to *How reallocation works* | "A seat is occupied **between stations**, not for the whole trip." |
| 2 | Anyone | Search **Kanpur → Lucknow**, today, Sleeper | "Sleeper is sold out on this segment." |
| 3 | Same | Search **New Delhi → Kanpur**, Sleeper | "But 50 berths are free here — availability is per segment." |
| 4 | TT (`tt_demo`) | Dashboard → *Open console* for 24051 → **Start run** | "The train is simulated; it is now halted at New Delhi." |
| 5 | TT | Search *Rahul* → **Did not board** → add remark → confirm | "Only now, after the train reached his station, can the TT release the seat. A boarded passenger could never be released." |
| 6 | TT | *Released seats* tab | "S1/25 is free from New Delhi onwards; the timeline shows each segment." |
| 7 | Passenger (`passenger`, other window) | Search Kanpur → Lucknow, Sleeper | "1 available — 1 released seat." |
| 8 | Passenger | Book → coach S1 → purple berth 25 → details → review → confirm | "Availability is re-checked inside a locked transaction." |
| 9 | Passenger | Booking page / e-ticket / PDF | "PNR, QR code, *Reallocated seat* badge." |
| 10 | `passenger2` | Book Lucknow → Varanasi, Sleeper, **Auto-pick** | "Best fit chooses S1/25 because the gap matches exactly." |
| 11 | Anyone | Search Kanpur → Varanasi, Sleeper | "Not available: it would overlap the Kanpur→Lucknow booking." |
| 12 | Admin (`admin`) | *Seat allocation* → S1 matrix; what-if S1-25 CNB→BSB | "Rejected — overlaps PNR … on CNB → LKO." |
| 13 | TT | **Depart New Delhi**, then search New Delhi → Kanpur | "Departed segments are never sold again." |
| 14 | Admin | Dashboard & Activity log | "Every action is audited; all numbers come from the database." |

**Terminal alternative:** `python manage.py run_demo_scenario` (rolled back; add `--commit` to keep).

**Likely viva questions**

- *How do you stop double booking?* IMMEDIATE transactions + re-validation inside the
  transaction + partial unique index on (seat, date, segment) where ACTIVE. See the
  threaded test in `apps/bookings/tests/test_concurrency.py`.
- *Why one row per segment?* Overlap becomes an indexed lookup and the database can
  enforce the rule itself.
- *Why can't B→D and C→E share a seat?* `[1,3)` and `[2,4)` both contain segment 2.
- *What if the TT marks the no-show late?* Only segments at/after the train's next
  boarding point become sellable (`min_boardable_index`).

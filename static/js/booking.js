/* Booking wizard: class & coach → seats → passengers → review → confirm.
   All availability comes from the Django API; the server re-validates everything on confirm. */
(function () {
  "use strict";
  const cfg = JSON.parse(document.getElementById("booking-config").textContent);
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const esc = SS.escape;

  const state = {
    step: "class",
    cls: cfg.selectedClass,
    pax: cfg.passengers,
    coaches: [],
    fares: {},
    coachId: null,
    selected: new Map(), // seatId -> {id, coachId, coach, number, berth, state}
    passengers: [],
  };
  const journeyParams = { from: cfg.from.code, to: cfg.to.code, date: cfg.date };
  const STEPS = ["class", "seats", "passengers", "review", "confirm"];

  /* ------------------------------------------------------------ navigation */
  function go(step) {
    state.step = step;
    $$(".wizard-pane").forEach((p) => p.classList.toggle("active", p.dataset.pane === step));
    const idx = STEPS.indexOf(step);
    $$("#stepper [data-step]").forEach((li) => {
      const i = STEPS.indexOf(li.dataset.step);
      li.classList.toggle("done", i < idx);
      li.classList.toggle("current", i === idx);
      li.querySelector(".num").innerHTML = i < idx ? '<i class="bi bi-check"></i>' : String(i + 3);
    });
    if (step === "seats") renderCoachTabs(), loadSeatMap();
    if (step === "passengers") renderPassengerCards();
    if (step === "review") renderReview();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-next]");
    if (!btn || btn.disabled) return;
    const target = btn.dataset.next;
    if (target === "seats" && !state.coachId) { SS.toast("Choose a coach with free seats first.", "warning"); return; }
    if (target === "passengers" && state.selected.size !== state.pax) {
      SS.toast(`Select ${state.pax} seat${state.pax > 1 ? "s" : ""} to continue.`, "warning"); return;
    }
    if (target === "passengers") collectPassengers(false);
    go(target);
  });

  /* --------------------------------------------------------------- summary */
  function classInfo(code) { return cfg.classes.find((c) => c.code === code); }
  function updateSummary() {
    const info = classInfo(state.cls);
    const fare = info ? info.fare : 0;
    $("#sumClass").textContent = info ? info.label : "—";
    const seats = Array.from(state.selected.values()).map((s) => `${s.coach}/${s.number}`);
    $("#sumSeats").textContent = seats.length ? seats.join(", ") : "—";
    $("#sumFareCalc").textContent = `${SS.money(fare)} × ${state.pax}`;
    $("#sumTotal").textContent = SS.money(fare * state.pax);
    $("#seatNeed").textContent = `${state.pax} seat${state.pax > 1 ? "s" : ""}`;
    $("#toPassengers").disabled = state.selected.size !== state.pax;
    renderSelectedChips();
  }

  /* --------------------------------------------------------- step 3: class */
  function renderClassTiles() {
    const wrap = $("#classTiles");
    wrap.innerHTML = cfg.classes.map((c) => {
      const off = c.available < state.pax;
      const tone = c.available === 0 ? "none" : c.available <= 5 ? "low" : "ok";
      return `<button type="button" role="radio" aria-checked="${c.code === state.cls}" class="class-tile text-start ${c.code === state.cls ? "is-selected" : ""} ${off ? "is-off" : ""}" data-cls="${c.code}" ${off ? "disabled" : ""}>
        <span class="cls"><span>${esc(c.code)}</span><span class="fare">${SS.money(c.fare)}</span></span>
        <span class="fs-xs text-muted">${esc(c.label.replace(/ \(.*\)/, ""))}</span>
        <span class="avail ${tone}">${c.available === 0 ? "Not available" : c.available + " available"}</span>
        ${c.reallocated ? `<span class="realloc-note"><i class="bi bi-arrow-repeat"></i> ${c.reallocated} released</span>` : ""}
      </button>`;
    }).join("");
    $$("[data-cls]", wrap).forEach((b) => b.addEventListener("click", () => {
      if (state.cls === b.dataset.cls) return;
      state.cls = b.dataset.cls;
      state.selected.clear();
      state.coachId = null;
      renderClassTiles();
      loadCoaches();
    }));
  }

  async function loadCoaches() {
    const grid = $("#coachGrid");
    grid.innerHTML = Array.from({ length: 4 }, () => `<div class="skeleton" style="height:78px"></div>`).join("");
    try {
      const data = await SS.api(cfg.urls.coaches, { params: { ...journeyParams, class: state.cls } });
      state.coaches = data.coaches;
      state.fares = data.fares;
      if (!state.coaches.find((c) => c.id === state.coachId)) {
        const first = state.coaches.find((c) => c.available > 0);
        state.coachId = first ? first.id : null;
      }
      renderCoachGrid();
    } catch (err) {
      grid.innerHTML = `<div class="callout callout-danger" style="grid-column:1/-1"><i class="bi bi-exclamation-octagon"></i><div>${esc(err.message)}</div></div>`;
    }
    updateSummary();
  }

  function renderCoachGrid() {
    const grid = $("#coachGrid");
    if (!state.coaches.length) {
      grid.innerHTML = `<div class="text-muted fs-sm" style="grid-column:1/-1">No coaches in this class.</div>`;
      return;
    }
    grid.innerHTML = state.coaches.map((c) => `
      <button type="button" class="coach-btn ${c.id === state.coachId ? "active" : ""}" data-coach="${c.id}" ${c.available === 0 ? "disabled" : ""} aria-pressed="${c.id === state.coachId}">
        <span class="cn">${esc(c.number)}</span>
        <span class="cs">${esc(c.coach_class)} · ${c.total} seats</span>
        <span class="ca" style="${c.available === 0 ? "color: var(--ss-red-600)" : ""}">${c.available} free${c.reallocated ? ` · <span style="color:var(--ss-violet-600)">${c.reallocated} released</span>` : ""}</span>
      </button>`).join("");
    $$("[data-coach]", grid).forEach((b) => b.addEventListener("click", () => {
      state.coachId = +b.dataset.coach;
      renderCoachGrid();
    }));
    $("#toSeats").disabled = !state.coachId;
  }

  function changePax(delta) {
    const next = Math.max(1, Math.min(cfg.maxPassengers, state.pax + delta));
    if (next === state.pax) return;
    state.pax = next;
    $("#paxCount").value = next;
    if (state.selected.size > next) {
      Array.from(state.selected.keys()).slice(next).forEach((k) => state.selected.delete(k));
    }
    renderClassTiles();
    updateSummary();
  }
  $("#paxMinus").addEventListener("click", () => changePax(-1));
  $("#paxPlus").addEventListener("click", () => changePax(1));

  /* --------------------------------------------------------- step 4: seats */
  function renderCoachTabs() {
    $("#coachTabs").innerHTML = state.coaches.filter((c) => c.available > 0 || c.id === state.coachId).map((c) =>
      `<button type="button" role="tab" class="${c.id === state.coachId ? "active" : ""}" data-tab="${c.id}" aria-selected="${c.id === state.coachId}">${esc(c.number)}</button>`).join("");
    $$("#coachTabs [data-tab]").forEach((b) => b.addEventListener("click", () => {
      state.coachId = +b.dataset.tab;
      renderCoachTabs();
      loadSeatMap();
    }));
  }

  function seatButton(s) {
    const sel = state.selected.has(s.id);
    const cls = sel ? "selected" : s.state;
    const title = s.state === "booked"
      ? `Seat ${s.number} · ${s.berth_label} · booked on ${s.occupied_on.join(", ")}`
      : `Seat ${s.number} · ${s.berth_label}${s.state === "reallocated" ? " · released by a no-show" : ""}`;
    return `<button type="button" class="seat ${cls}" data-seat="${s.id}" ${s.state === "booked" ? "disabled" : ""} title="${esc(title)}" aria-label="${esc(title)}" aria-pressed="${sel}">
      ${s.number}<small>${esc(s.berth)}</small></button>`;
  }

  let seatData = null;
  async function loadSeatMap() {
    const map = $("#seatMap");
    if (!state.coachId) { map.innerHTML = ""; return; }
    map.innerHTML = `<div class="d-flex gap-2">${Array.from({ length: 6 }, () => `<div class="skeleton" style="width:110px;height:150px"></div>`).join("")}</div>`;
    try {
      seatData = await SS.api(cfg.urls.seatMap, { params: { ...journeyParams, coach: state.coachId } });
      // Drop selections that are no longer free (someone else booked them meanwhile).
      seatData.seats.forEach((s) => { if (s.state === "booked" && state.selected.has(s.id)) state.selected.delete(s.id); });
      map.innerHTML = SS.coachLayout(seatData.coach, seatData.seats, seatButton);
      $$("[data-seat]", map).forEach((b) => b.addEventListener("click", () => toggleSeat(+b.dataset.seat)));
    } catch (err) {
      map.innerHTML = `<div class="callout callout-danger"><i class="bi bi-exclamation-octagon"></i><div>${esc(err.message)}</div></div>`;
    }
    updateSummary();
  }

  function toggleSeat(id) {
    const seat = seatData.seats.find((s) => s.id === id);
    if (!seat || seat.state === "booked") return;
    if (state.selected.has(id)) {
      state.selected.delete(id);
    } else {
      if (state.selected.size >= state.pax) {
        SS.toast(`You need ${state.pax} seat${state.pax > 1 ? "s" : ""}. Remove one before choosing another, or add a passenger.`, "warning", { timeout: 3500 });
        return;
      }
      state.selected.set(id, { id, coachId: seatData.coach.id, coach: seatData.coach.number, number: seat.number, berth: seat.berth, state: seat.state });
    }
    const btn = $(`[data-seat="${id}"]`);
    btn.className = `seat ${state.selected.has(id) ? "selected" : seat.state}`;
    btn.setAttribute("aria-pressed", state.selected.has(id));
    updateSummary();
  }

  function renderSelectedChips() {
    const wrap = $("#selectedSeats");
    if (!wrap) return;
    const items = Array.from(state.selected.values());
    wrap.innerHTML = items.length
      ? `<span class="fs-sm text-muted me-1">Selected:</span>` + items.map((s) =>
          `<span class="chip ${s.state === "reallocated" ? "chip-realloc" : "chip-info"} no-dot">${esc(s.coach)}/${s.number} · ${esc(s.berth)}
           <button type="button" class="btn p-0 border-0 ms-1" data-unselect="${s.id}" aria-label="Remove seat ${s.number}" style="line-height:1;color:inherit"><i class="bi bi-x"></i></button></span>`).join("")
      : `<span class="fs-sm text-muted">No seats selected yet — tap a green seat or use Auto-pick.</span>`;
    $$("[data-unselect]", wrap).forEach((b) => b.addEventListener("click", () => {
      const id = +b.dataset.unselect;
      state.selected.delete(id);
      const seatBtn = $(`[data-seat="${id}"]`);
      if (seatBtn && seatData) {
        const s = seatData.seats.find((x) => x.id === id);
        seatBtn.className = `seat ${s ? s.state : "available"}`;
      }
      updateSummary();
    }));
  }

  $("#autoPick").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    SS.setLoading(btn, true, "Finding…");
    try {
      const prefs = state.passengers.map((p) => p.berth_preference || "").join(",");
      const data = await SS.api(cfg.urls.suggest, { params: { ...journeyParams, class: state.cls, count: state.pax, prefs } });
      state.selected.clear();
      const coachId = data.seats[0].coach_id;
      state.coachId = coachId;
      renderCoachTabs();
      await loadSeatMap();
      data.seats.forEach((s) => {
        const info = seatData.seats.find((x) => x.id === s.id);
        state.selected.set(s.id, { id: s.id, coachId: s.coach_id, coach: s.coach, number: s.number, berth: s.berth, state: info ? info.state : "available" });
        const b = $(`[data-seat="${s.id}"]`);
        if (b) b.className = "seat selected";
      });
      updateSummary();
      SS.toast(`Picked ${data.seats.map((s) => s.coach + "/" + s.number).join(", ")} using best-fit allocation.`, "success", { timeout: 3500 });
    } catch (err) {
      SS.toast(err.message, "danger");
    } finally {
      SS.setLoading(btn, false);
    }
  });

  /* ---------------------------------------------------- step 5: passengers */
  function collectPassengers(validate) {
    const cards = $$("#paxCards .passenger-card");
    if (!cards.length) return true;
    let ok = true;
    state.passengers = cards.map((card) => {
      const get = (n) => card.querySelector(`[name=${n}]`);
      const p = { name: get("name").value.trim(), age: get("age").value.trim(), gender: get("gender").value, berth_preference: get("berth").value };
      if (validate) {
        const nameOk = /^[A-Za-z][A-Za-z .'-]{1,79}$/.test(p.name);
        const ageOk = /^\d{1,3}$/.test(p.age) && +p.age >= 1 && +p.age <= 120;
        get("name").classList.toggle("is-invalid", !nameOk);
        get("age").classList.toggle("is-invalid", !ageOk);
        get("gender").classList.toggle("is-invalid", !p.gender);
        ok = ok && nameOk && ageOk && !!p.gender;
      }
      return p;
    });
    return ok;
  }

  function renderPassengerCards() {
    const seats = Array.from(state.selected.values());
    const prev = state.passengers;
    const wrap = $("#paxCards");
    const berthOptions = (val) => `<option value="">No preference</option>` + cfg.berths.map((b) =>
      `<option value="${b.code}" ${val === b.code ? "selected" : ""}>${esc(b.label)}</option>`).join("");
    wrap.innerHTML = seats.map((s, i) => {
      const p = prev[i] || (i === 0 ? { name: cfg.user.name, age: cfg.user.age, gender: cfg.user.gender, berth_preference: cfg.user.berth } : {});
      return `<div class="passenger-card">
        <div class="d-flex justify-content-between align-items-center mb-2">
          <span class="p-index">Passenger ${i + 1}</span>
          <span class="seat-tag">Seat ${esc(s.coach)}/${s.number} · ${esc(s.berth)}</span>
        </div>
        <div class="row g-3">
          <div class="col-md-5"><label class="form-label" for="pn${i}">Full name</label>
            <input class="form-control" id="pn${i}" name="name" maxlength="80" value="${esc(p.name || "")}" autocomplete="${i === 0 ? "name" : "off"}" required>
            <div class="invalid-feedback">Letters, spaces, dots and hyphens only.</div></div>
          <div class="col-4 col-md-2"><label class="form-label" for="pa${i}">Age</label>
            <input class="form-control" id="pa${i}" name="age" type="number" min="1" max="120" value="${esc(p.age || "")}" required>
            <div class="invalid-feedback">1–120</div></div>
          <div class="col-8 col-md-2"><label class="form-label" for="pg${i}">Gender</label>
            <select class="form-select" id="pg${i}" name="gender" required>
              <option value="">Select</option>
              <option value="F" ${p.gender === "F" ? "selected" : ""}>Female</option>
              <option value="M" ${p.gender === "M" ? "selected" : ""}>Male</option>
              <option value="O" ${p.gender === "O" ? "selected" : ""}>Other</option>
            </select><div class="invalid-feedback">Required</div></div>
          <div class="col-md-3"><label class="form-label" for="pb${i}">Berth preference</label>
            <select class="form-select" id="pb${i}" name="berth">${berthOptions(p.berth_preference || "")}</select></div>
        </div></div>`;
    }).join("");
    if (!$("#contactEmail").value) $("#contactEmail").value = cfg.user.email || "";
    if (!$("#contactPhone").value) $("#contactPhone").value = cfg.user.phone || "";
  }

  $("#paxForm").addEventListener("submit", (e) => {
    e.preventDefault();
    const ok = collectPassengers(true);
    const email = $("#contactEmail"), phone = $("#contactPhone");
    const emailOk = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.value.trim());
    const phoneOk = !phone.value || /^[6-9]\d{9}$/.test(phone.value.trim());
    email.classList.toggle("is-invalid", !emailOk);
    phone.classList.toggle("is-invalid", !phoneOk);
    if (!ok || !emailOk || !phoneOk) {
      SS.toast("Please fix the highlighted fields.", "warning");
      const first = $("#paxForm .is-invalid");
      if (first) first.focus();
      return;
    }
    go("review");
  });

  /* --------------------------------------------------------- step 6: review */
  function renderReview() {
    const info = classInfo(state.cls);
    const seats = Array.from(state.selected.values());
    const gender = { M: "Male", F: "Female", O: "Other" };
    const realloc = seats.filter((s) => s.state === "reallocated").length;
    $("#reviewBody").innerHTML = `
      <div class="kv mb-4">
        <div><div class="k">Train</div><div class="v"><span class="train-no">${esc(cfg.trainNumber)}</span> ${esc(cfg.trainName)}</div></div>
        <div><div class="k">Journey</div><div class="v">${esc(cfg.from.name)} → ${esc(cfg.to.name)}</div></div>
        <div><div class="k">Date</div><div class="v">${esc(cfg.dateLabel)}</div></div>
        <div><div class="k">Class</div><div class="v">${esc(info.label)}</div></div>
      </div>
      ${realloc ? `<div class="callout callout-info mb-3"><i class="bi bi-arrow-repeat"></i><div>${realloc} of your seats ${realloc > 1 ? "were" : "was"} released after a verified no-show — a reallocated seat is a normal confirmed seat for your segments.</div></div>` : ""}
      <div class="table-responsive border rounded-3">
        <table class="table table-ss mb-0">
          <thead><tr><th>#</th><th>Passenger</th><th>Age</th><th>Gender</th><th>Seat</th><th class="text-end">Fare</th></tr></thead>
          <tbody>${state.passengers.map((p, i) => `<tr>
            <td>${i + 1}</td><td class="cell-title">${esc(p.name)}</td><td>${esc(p.age)}</td><td>${gender[p.gender]}</td>
            <td><span class="mono fw-650">${esc(seats[i].coach)}/${seats[i].number}</span> <span class="text-muted fs-xs">${esc(seats[i].berth)}</span>${seats[i].state === "reallocated" ? ' <span class="chip chip-realloc no-dot">released</span>' : ""}</td>
            <td class="text-end tabular">${SS.money(info.fare)}</td></tr>`).join("")}</tbody>
        </table>
      </div>
      <div class="d-flex justify-content-end mt-3"><div style="min-width:260px">
        <div class="summary-row"><span class="k">Fare per passenger</span><span class="v">${SS.money(info.fare)}</span></div>
        <div class="summary-row"><span class="k">Passengers</span><span class="v">${state.pax}</span></div>
        <div class="summary-row"><span class="k">Contact</span><span class="v">${esc($("#contactEmail").value)}</span></div>
        <div class="divider my-2"></div>
        <div class="d-flex justify-content-between align-items-end"><span class="text-muted fs-sm">Total payable (simulated)</span><span class="summary-total">${SS.money(info.fare * state.pax)}</span></div>
      </div></div>`;
    $("#agree").checked = false;
    $("#confirmBtn").disabled = true;
  }
  $("#agree").addEventListener("change", (e) => { $("#confirmBtn").disabled = !e.target.checked; });

  /* -------------------------------------------------------- step 7: confirm */
  $("#confirmBtn").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    SS.setLoading(btn, true, "Confirming seats…");
    $$("#stepper [data-step]").forEach((li) => { if (li.dataset.step === "confirm") li.classList.add("current"); });
    try {
      const data = await SS.api(cfg.urls.create, {
        method: "POST",
        body: {
          train_id: cfg.trainId,
          journey_date: cfg.date,
          from_code: cfg.from.code,
          to_code: cfg.to.code,
          coach_class: state.cls,
          seat_ids: Array.from(state.selected.keys()),
          passengers: state.passengers.map((p) => ({ ...p, age: +p.age })),
          contact_email: $("#contactEmail").value.trim(),
          contact_phone: $("#contactPhone").value.trim(),
        },
      });
      SS.toast(`PNR ${data.pnr} confirmed.`, "success", { title: "Booking confirmed" });
      window.location.href = data.redirect_url;
    } catch (err) {
      SS.setLoading(btn, false);
      if (err.status === 409 && ["seat_unavailable", "race_lost", "invalid_seat"].includes(err.code)) {
        SS.toast(err.message, "danger", { title: "Seat no longer available", timeout: 8000 });
        await loadCoaches();
        go("seats");
      } else {
        SS.toast(err.message, "danger", { title: "Booking not completed", timeout: 8000 });
      }
    }
  });

  /* ------------------------------------------------------------------ init */
  renderClassTiles();
  loadCoaches();
  updateSummary();
})();

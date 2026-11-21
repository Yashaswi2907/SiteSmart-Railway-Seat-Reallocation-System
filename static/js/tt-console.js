/* TT/TTE run console: simulation controls, passenger verification, occupancy and released seats. */
(function () {
  "use strict";
  const cfg = JSON.parse(document.getElementById("console-config").textContent);
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const esc = SS.escape;
  const state = { sim: null, coaches: [], scope: "", tab: "passengers", occCoach: null, occSegment: null, lastStatusKey: "" };

  /* ------------------------------------------------------------- status */
  function renderTracker(sim) {
    const n = sim.stops.length;
    const pct = n > 1 ? (sim.status === "COMPLETED" ? 100 : sim.status === "SCHEDULED" ? 0
      : ((sim.current_index + (sim.status === "IN_TRANSIT" ? 0.5 : 0)) / (n - 1)) * 100) : 0;
    const trainLeft = (100 / n) / 2 + (pct / 100) * (100 - 100 / n);
    $("#tracker").innerHTML = `
      <div class="tracker-rail" style="--stops:${n}">
        <div class="tracker-progress" style="width: calc(${pct / 100} * (100% - 100% / ${n}))"></div>
        ${sim.status !== "SCHEDULED" && sim.status !== "COMPLETED" ? `<i class="bi bi-train-front-fill tracker-train" style="left:${trainLeft}%" aria-hidden="true"></i>` : ""}
        ${sim.stops.map((s) => `
          <div class="tracker-stop ${s.state}">
            <span class="dot">${s.state === "passed" ? '<i class="bi bi-check"></i>' : ""}</span>
            <span class="code">${esc(s.code)}</span><span class="nm">${esc(s.name)}</span>
            <span class="tm">${s.arrival || ""}${s.arrival && s.departure ? " · " : ""}${s.departure || ""}</span>
          </div>`).join("")}
      </div>`;
    $("#runProgress").style.width = sim.progress + "%";
  }

  function renderControls(sim) {
    const running = sim.status === "AT_STATION" || sim.status === "IN_TRANSIT";
    $("#btnStart").hidden = !sim.can_start;
    $("#btnStep").hidden = !running;
    $("#btnNext").hidden = !(running && sim.status === "AT_STATION" && sim.current_index < sim.stops.length - 1);
    $("#btnPause").hidden = !running;
    $("#autoWrap").hidden = !running;
    $("#btnStep span").textContent = sim.next_action || "Step";
    $("#btnStep").disabled = sim.is_paused;
    $("#btnNext").disabled = sim.is_paused;
    $("#btnPause").innerHTML = sim.is_paused ? '<i class="bi bi-play-fill"></i> Resume' : '<i class="bi bi-pause-fill"></i> Pause';
    $("#autoToggle").checked = sim.auto_advance;
    $("#autoInterval").value = String(sim.step_interval_seconds);
    $("#runPulse").className = "pulse" + (running ? (sim.is_paused ? " paused" : "") : " idle");
    $("#runHeadline").textContent = sim.headline + (sim.is_paused ? " (paused)" : "");
    let sub = `${sim.status_label}`;
    if (running) sub += ` · new bookings may board from ${sim.stops[Math.min(sim.min_boardable_index, sim.stops.length - 1)].name} onwards`;
    if (sim.auto_advance && running && !sim.is_paused) sub += ` · auto-advancing every ${sim.step_interval_seconds}s`;
    if (sim.status === "SCHEDULED" && !sim.can_start) sub += " · runs can be started on or after their run date";
    $("#runSub").textContent = sub;
  }

  function renderStats(st) {
    $("#stTotal").textContent = st.total;
    $("#stBoarded").textContent = st.boarded;
    $("#stNb").textContent = st.not_boarded;
    $("#stPendingHere").textContent = st.pending_here;
    $("#stReleased").textContent = st.released_seats;
    $("#stUtil").textContent = st.utilisation + "%";
    $("#relCount").textContent = st.released_seats;
  }

  async function loadConsole() {
    try {
      const data = await SS.api(cfg.urls.console);
      const sim = data.simulation;
      const key = `${sim.status}-${sim.current_index}-${sim.is_paused}`;
      const moved = state.sim && key !== state.lastStatusKey;
      state.sim = sim;
      state.lastStatusKey = key;
      if (!state.coaches.length) {
        state.coaches = data.coaches;
        const opts = data.coaches.map((c) => `<option value="${c.id}">${esc(c.number)} · ${esc(c.coach_class)}</option>`).join("");
        $("#fCoach").insertAdjacentHTML("beforeend", opts);
        $("#occCoach").innerHTML = opts;
      }
      renderTracker(sim);
      renderControls(sim);
      renderStats(data.stats);
      if (moved) { loadPassengers(); refreshTab(); }
    } catch (err) {
      $("#runHeadline").textContent = "Could not load run";
      $("#runSub").textContent = err.message;
    }
  }

  async function control(action, extra = {}) {
    try {
      const data = await SS.api(cfg.urls.control, { method: "POST", body: { action, ...extra } });
      state.sim = data.simulation;
      state.lastStatusKey = `${data.simulation.status}-${data.simulation.current_index}-${data.simulation.is_paused}`;
      renderTracker(data.simulation);
      renderControls(data.simulation);
      renderStats(data.stats);
      loadPassengers();
      refreshTab();
      return data.simulation;
    } catch (err) {
      SS.toast(err.message, "danger");
      return null;
    }
  }

  $("#btnStart").addEventListener("click", async (e) => {
    const { confirmed } = await SS.confirm({
      title: "Start this run?", message: `Train ${cfg.trainNumber} will be placed at its origin station. From then on, departed segments can no longer be sold.`,
      confirmText: "Start run", tone: "success", icon: "bi-play-fill",
    });
    if (!confirmed) return;
    SS.setLoading(e.currentTarget, true, "Starting…");
    const sim = await control("start");
    SS.setLoading($("#btnStart"), false);
    if (sim) SS.toast(sim.headline, "success", { title: "Run started" });
  });
  $("#btnStep").addEventListener("click", async (e) => {
    const label = state.sim ? state.sim.next_action : "";
    SS.setLoading(e.currentTarget, true, "Moving…");
    const sim = await control("step");
    SS.setLoading($("#btnStep"), false);
    if (sim) { renderControls(sim); SS.toast(sim.headline, "info", { title: label, timeout: 2800 }); }
  });
  $("#btnNext").addEventListener("click", async (e) => {
    SS.setLoading(e.currentTarget, true, "Moving…");
    const sim = await control("next_station");
    SS.setLoading($("#btnNext"), false);
    if (sim) { renderControls(sim); SS.toast(sim.headline, "info", { timeout: 2800 }); }
  });
  $("#btnPause").addEventListener("click", () => control(state.sim && state.sim.is_paused ? "resume" : "pause"));
  $("#autoToggle").addEventListener("change", (e) => control(e.target.checked ? "auto_on" : "auto_off", { interval: +$("#autoInterval").value }));
  $("#autoInterval").addEventListener("change", () => { if ($("#autoToggle").checked) control("auto_on", { interval: +$("#autoInterval").value }); });

  /* --------------------------------------------------------- passengers */
  const STATUS_CHIP = { PENDING: "secondary", BOARDED: "success", NOT_BOARDED: "warning" };
  function paxRow(p) {
    const actions = p.can_verify
      ? `<div class="d-inline-flex gap-1">
           <button class="btn btn-sm btn-outline-success" data-verify="BOARDED" data-id="${p.id}"><i class="bi bi-person-check"></i> Boarded</button>
           <button class="btn btn-sm btn-outline-danger" data-verify="NOT_BOARDED" data-id="${p.id}"><i class="bi bi-person-x"></i> Did not board</button>
         </div>`
      : `<span class="fs-xs text-muted" title="${esc(p.verify_block_reason)}">${p.boarding_status === "PENDING" ? esc(p.verify_block_reason) : `<i class="bi bi-lock"></i> Final`}</span>`;
    return `<tr data-row="${p.id}">
      <td><span class="pnr">${esc(p.pnr)}</span></td>
      <td><div class="cell-title">${esc(p.name)}</div><div class="cell-sub">${p.age} · ${p.gender}${p.is_reallocated ? ' · <span style="color:var(--ss-violet-600)">reallocated seat</span>' : ""}</div></td>
      <td><span class="mono fw-650 text-ink">${esc(p.coach)}/${p.seat_number}</span> <span class="cell-sub">${esc(p.berth)}</span></td>
      <td><span class="code-pill">${esc(p.from_code)}</span> <i class="bi bi-arrow-right text-muted"></i> <span class="code-pill">${esc(p.to_code)}</span>
          ${p.boards_here ? '<span class="chip chip-info ms-1">boards here</span>' : ""}${p.deboards_next ? '<span class="chip chip-neutral ms-1">alights next</span>' : ""}</td>
      <td><span class="chip chip-${STATUS_CHIP[p.boarding_status]}">${esc(p.boarding_label)}</span>${p.verified_at ? `<div class="cell-sub mt-1">${esc(p.verified_by || "")} · ${esc(p.verified_at)}</div>` : ""}</td>
      <td class="text-end">${actions}</td></tr>`;
  }

  let paxController = null;
  async function loadPassengers() {
    if (paxController) paxController.abort();
    paxController = new AbortController();
    try {
      const data = await SS.api(cfg.urls.passengers, {
        params: { q: $("#fQ").value.trim(), coach: $("#fCoach").value, status: $("#fStatus").value, scope: state.scope },
        signal: paxController.signal,
      });
      $("#paxCount").textContent = data.count;
      $("#paxBody").innerHTML = data.results.length ? data.results.map(paxRow).join("")
        : `<tr><td colspan="6"><div class="empty-state py-4"><div class="icon-wrap"><i class="bi bi-people"></i></div><h3>No passengers match</h3><p>Change the filters, or book tickets on this run to see them here.</p></div></td></tr>`;
    } catch (err) {
      if (err.name !== "AbortError") $("#paxBody").innerHTML = `<tr><td colspan="6"><div class="callout callout-danger m-2"><i class="bi bi-exclamation-octagon"></i><div>${esc(err.message)}</div></div></td></tr>`;
    }
  }

  let qTimer;
  $("#fQ").addEventListener("input", () => { clearTimeout(qTimer); qTimer = setTimeout(loadPassengers, 250); });
  $("#fCoach").addEventListener("change", loadPassengers);
  $("#fStatus").addEventListener("change", loadPassengers);
  $$("#fScope button").forEach((b) => b.addEventListener("click", () => {
    $$("#fScope button").forEach((x) => x.classList.toggle("active", x === b));
    state.scope = b.dataset.scope;
    loadPassengers();
  }));

  $("#paxBody").addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-verify]");
    if (!btn) return;
    const row = btn.closest("tr");
    const name = row.querySelector(".cell-title").textContent;
    const seat = row.children[2].textContent.trim();
    const noShow = btn.dataset.verify === "NOT_BOARDED";
    const res = await SS.confirm({
      title: noShow ? `Mark ${name} as did not board?` : `Confirm ${name} is on board?`,
      message: noShow
        ? `Seat ${seat} will be released for every remaining segment and immediately offered to passengers boarding at upcoming stations. This cannot be undone.`
        : `The passenger will be recorded as boarded. Their seat can never be released as a no-show afterwards.`,
      confirmText: noShow ? "Mark did not board" : "Mark boarded",
      tone: noShow ? "danger" : "success",
      icon: noShow ? "bi-person-x" : "bi-person-check",
      input: { label: "Remarks (optional)", placeholder: noShow ? "e.g. not present at berth after departure" : "e.g. ID checked" },
    });
    if (!res.confirmed) return;
    SS.setLoading(btn, true, "Saving…");
    try {
      const data = await SS.api(cfg.urls.verify.replace("{id}", btn.dataset.id), { method: "POST", body: { status: btn.dataset.verify, remarks: res.value } });
      row.outerHTML = paxRow(data.passenger);
      SS.toast(data.message, noShow ? "warning" : "success", { title: noShow ? "Seat released" : "Verified", timeout: 7000 });
      loadConsole();
      refreshTab();
    } catch (err) {
      SS.setLoading(btn, false);
      SS.toast(err.message, "danger", { title: "Not updated" });
    }
  });

  /* ---------------------------------------------------------- occupancy */
  async function loadOccupancy() {
    const map = $("#occMap");
    map.innerHTML = `<div class="skeleton" style="height:160px"></div>`;
    try {
      const data = await SS.api(cfg.urls.occupancy, { params: { coach: $("#occCoach").value, segment: state.occSegment ?? undefined } });
      if (!data.coach) { map.innerHTML = `<p class="text-muted mb-0">No coaches on this train.</p>`; return; }
      const segSel = $("#occSegment");
      segSel.innerHTML = data.segments.map((s) => `<option value="${s.index}" ${s.index === data.segment ? "selected" : ""}>Segment ${esc(s.label)}</option>`).join("");
      $("#occLabel").textContent = `Coach ${data.coach.number} between ${data.segment_label}`;
      const seatFn = (s) => {
        const tip = s.pnr ? `${s.number} ${s.berth} · PNR ${s.pnr}${s.name ? " · " + s.name : ""}${s.journey ? " · " + s.journey : ""}` : `${s.number} ${s.berth} · vacant`;
        return `<button type="button" class="seat occ-${s.state}" title="${esc(tip)}" aria-label="${esc(tip)}" tabindex="0">${s.number}<small>${esc(s.berth)}</small></button>`;
      };
      map.innerHTML = SS.coachLayout(data.coach, data.seats, seatFn);
    } catch (err) {
      map.innerHTML = `<div class="callout callout-danger"><i class="bi bi-exclamation-octagon"></i><div>${esc(err.message)}</div></div>`;
    }
  }
  $("#occCoach").addEventListener("change", () => { state.occSegment = null; loadOccupancy(); });
  $("#occSegment").addEventListener("change", (e) => { state.occSegment = +e.target.value; loadOccupancy(); });

  /* ----------------------------------------------------------- released */
  async function loadReleased() {
    const body = $("#relBody");
    body.innerHTML = `<div class="skeleton sk-block"></div>`;
    try {
      const data = await SS.api(cfg.urls.released);
      $("#relCount").textContent = data.count;
      if (!data.count) {
        body.innerHTML = `<div class="empty-state py-4"><div class="icon-wrap"><i class="bi bi-arrow-repeat"></i></div><h3>No released seats yet</h3><p>When you mark a passenger as “Did not board”, their seat appears here with the journeys it can still serve.</p></div>`;
        return;
      }
      body.innerHTML = data.results.map((r) => {
        const segs = r.timeline.map((t) => {
          const cls = t.departed ? "is-departed" : t.state === "occupied" ? (t.is_reallocation ? "is-realloc" : "is-taken") : t.state === "released" ? "is-released" : "is-free";
          const tip = t.state === "occupied" ? `${t.from_code}→${t.to_code} · PNR ${t.pnr}` : `${t.from_code}→${t.to_code} · ${t.departed ? "travelled" : t.state}`;
          return `<div class="seg ${cls}" title="${esc(tip)}">${esc(t.from_code)}–${esc(t.to_code)}</div>`;
        }).join("");
        const ranges = r.eligible_ranges.length
          ? r.eligible_ranges.map((g) => `<a class="chip chip-success no-dot text-decoration-none" href="${cfg.urls.search}?from=${g.from_code}&to=${g.to_code}&date=${cfg.date}&class=${r.coach_class}" target="_blank" rel="noopener">${esc(g.from_code)} → ${esc(g.to_code)} <i class="bi bi-box-arrow-up-right"></i></a>`).join(" ")
          : `<span class="fs-sm text-muted">No sellable segments remain — fully reallocated or already travelled.</span>`;
        return `<div class="released-card">
          <div class="d-flex flex-wrap justify-content-between gap-2 mb-2">
            <div><span class="mono fw-650 text-ink fs-5">${esc(r.seat_label)}</span> <span class="text-muted fs-sm">${esc(r.berth)} · ${esc(r.coach_class)}</span></div>
            <div class="fs-sm text-muted">${r.no_shows.map((n) => `No-show: <strong class="text-ink">${esc(n.passenger)}</strong> (PNR <span class="pnr">${esc(n.pnr)}</span>, ${esc(n.from_code)}→${esc(n.to_code)})${n.verified_by ? " · verified by " + esc(n.verified_by) : ""}`).join("<br>")}</div>
          </div>
          <div class="seg-track mb-2" style="--segs:${r.timeline.length}">${segs}</div>
          <div class="d-flex flex-wrap gap-2 align-items-center"><span class="small-caps me-1">Eligible now</span>${ranges}</div>
        </div>`;
      }).join("") + `<div class="legend mt-3"><span><i class="sw" style="background:var(--ss-navy-700)"></i>Original / other booking</span><span><i class="sw" style="background:var(--ss-violet-600)"></i>Reallocated booking</span><span><i class="sw" style="background:#F6E7C3;border-color:#EBCF8E"></i>Released, free</span><span><i class="sw" style="background:var(--ss-green-50);border-color:#BFE6CD"></i>Free</span><span><i class="sw" style="background:#E9EDF3"></i>Already travelled</span></div>`;
    } catch (err) {
      body.innerHTML = `<div class="callout callout-danger"><i class="bi bi-exclamation-octagon"></i><div>${esc(err.message)}</div></div>`;
    }
  }

  /* ---------------------------------------------------------------- tabs */
  function refreshTab() {
    if (state.tab === "occupancy") loadOccupancy();
    if (state.tab === "released") loadReleased();
  }
  $$(".ss-tabs [data-tab]").forEach((b) => b.addEventListener("click", () => {
    state.tab = b.dataset.tab;
    $$(".ss-tabs [data-tab]").forEach((x) => { x.classList.toggle("active", x === b); x.setAttribute("aria-selected", x === b); });
    $$("[data-panel]").forEach((p) => { p.hidden = p.dataset.panel !== state.tab; });
    if (state.tab === "occupancy") state.occSegment = null;
    refreshTab();
  }));

  /* ---------------------------------------------------------------- init */
  loadConsole().then(() => { loadPassengers(); loadReleased(); });
  setInterval(loadConsole, 5000);
})();

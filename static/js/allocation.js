/* Admin seat-allocation monitor: seat x segment matrix and the what-if allocation checker. */
(function () {
  "use strict";
  const cfgEl = document.getElementById("alloc-config");
  if (!cfgEl) return;
  const cfg = JSON.parse(cfgEl.textContent);
  const esc = SS.escape;
  let coachId = null;

  async function loadMatrix() {
    const wrap = document.getElementById("matrix");
    wrap.innerHTML = `<div class="skeleton sk-block m-3"></div>`;
    try {
      const m = await SS.api(cfg.matrix, { params: { train: cfg.train, date: cfg.date, coach: coachId } });
      if (!m.coach) { wrap.innerHTML = `<p class="text-muted p-3 mb-0">No coaches or route configured.</p>`; return; }
      coachId = m.coach.id;
      const seatSel = document.getElementById("ckSeat");
      seatSel.innerHTML = m.rows.map((r) => `<option value="${r.seat_id}">${esc(m.coach.number)}-${r.number} (${esc(r.berth)})</option>`).join("");
      wrap.innerHTML = `<table class="matrix"><thead><tr><th>Seat</th>${m.segments.map((s) => `<th>${esc(s)}</th>`).join("")}</tr></thead><tbody>
        ${m.rows.map((r) => `<tr><td class="mono fw-650 text-ink">${r.number} <span class="text-muted fw-normal">${esc(r.berth)}</span></td>
          ${r.cells.map((c, i) => {
            const cls = `cell ${c.s}${c.r ? " r" : ""}${c.d ? " d" : ""}`;
            const tip = `${m.coach.number}-${r.number} · ${m.segments[i]} · ${c.s === "A" ? "PNR " + c.pnr : c.s === "R" ? "released (PNR " + c.pnr + " no-show)" : "free"}${c.d ? " · departed" : ""}`;
            return `<td><div class="${cls}" title="${esc(tip)}" data-seat="${r.seat_id}">${c.s === "A" ? esc(c.pnr.slice(-4)) : c.s === "R" ? "rel" : ""}</div></td>`;
          }).join("")}</tr>`).join("")}</tbody></table>`;
      wrap.querySelectorAll("[data-seat]").forEach((el) => el.addEventListener("click", () => {
        seatSel.value = el.dataset.seat;
        seatSel.dispatchEvent(new Event("change"));
        SS.toast(`Seat ${seatSel.options[seatSel.selectedIndex].text} selected in the checker.`, "info", { timeout: 1800 });
      }));
    } catch (err) {
      wrap.innerHTML = `<div class="callout callout-danger m-3"><i class="bi bi-exclamation-octagon"></i><div>${esc(err.message)}</div></div>`;
    }
  }

  document.querySelectorAll("#coachTabs [data-coach]").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll("#coachTabs [data-coach]").forEach((x) => x.classList.toggle("active", x === b));
    coachId = +b.dataset.coach;
    loadMatrix();
  }));

  document.getElementById("checkForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const out = document.getElementById("ckResult");
    const btn = e.currentTarget.querySelector("[type=submit]");
    SS.setLoading(btn, true, "Checking…");
    try {
      const r = await SS.api(cfg.check, { params: { train: cfg.train, date: cfg.date, seat: document.getElementById("ckSeat").value,
        from: document.getElementById("ckFrom").value, to: document.getElementById("ckTo").value } });
      const conflictSegs = new Set(r.conflicts.map((c) => c.segment_index));
      const req = new Set(r.requested_indices);
      const segs = r.timeline.map((t) => {
        let cls = t.departed ? "is-departed" : t.state === "occupied" ? (t.is_reallocation ? "is-realloc" : "is-taken") : t.state === "released" ? "is-released" : "is-free";
        if (req.has(t.segment_index) && conflictSegs.has(t.segment_index)) cls = "is-conflict";
        return `<div class="seg ${cls}" style="${req.has(t.segment_index) ? "outline:2px solid var(--ss-blue-500);outline-offset:1px" : ""}" title="${esc(t.from_code)}→${esc(t.to_code)}">${esc(t.from_code)}–${esc(t.to_code)}</div>`;
      }).join("");
      out.innerHTML = `<div class="callout ${r.bookable ? "callout-success" : "callout-danger"} mb-3"><i class="bi ${r.bookable ? "bi-check-circle" : "bi-x-octagon"}"></i>
          <div><strong>${r.bookable ? "Allowed" : "Rejected"}</strong> — seat ${esc(r.seat)}, ${esc(r.journey)}<div class="fs-sm mt-1">${esc(r.verdict)}</div></div></div>
        <div class="small-caps mb-1">Seat timeline (requested segments outlined)</div>
        <div class="seg-track mb-2" style="--segs:${r.timeline.length}">${segs}</div>
        <div class="fs-xs text-muted">Overlap test: [${r.requested_indices[0]}, ${r.requested_indices[r.requested_indices.length - 1] + 1}) against every ACTIVE allocation · position check: ${r.position_ok ? "ahead of train ✓" : "departed ✗"}</div>`;
    } catch (err) {
      out.innerHTML = `<div class="callout callout-danger"><i class="bi bi-exclamation-octagon"></i><div>${esc(err.message)}</div></div>`;
    } finally {
      SS.setLoading(btn, false);
    }
  });

  loadMatrix();
})();

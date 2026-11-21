/* SiteSmart Rail — shared front-end utilities (no framework, no build step). */
(function () {
  "use strict";

  const SS = (window.SS = window.SS || {});

  /* ---------------------------------------------------------------- CSRF + fetch */
  function getCookie(name) {
    const match = document.cookie.match(new RegExp("(^|;\\s*)" + name + "=([^;]*)"));
    return match ? decodeURIComponent(match[2]) : null;
  }

  class ApiError extends Error {
    constructor(message, status, code, details) {
      super(message);
      this.status = status;
      this.code = code;
      this.details = details || {};
    }
  }
  SS.ApiError = ApiError;

  /**
   * JSON fetch wrapper that talks to the Django REST API.
   * Throws ApiError with the server's human-readable message on failure.
   */
  SS.api = async function (url, { method = "GET", body, params, signal } = {}) {
    if (params) {
      const qs = new URLSearchParams();
      Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== "") qs.append(k, v); });
      const s = qs.toString();
      if (s) url += (url.includes("?") ? "&" : "?") + s;
    }
    const headers = { Accept: "application/json" };
    if (method !== "GET") {
      headers["Content-Type"] = "application/json";
      headers["X-CSRFToken"] = getCookie("csrftoken") || "";
    }
    let response;
    try {
      response = await fetch(url, { method, headers, body: body ? JSON.stringify(body) : undefined, credentials: "same-origin", signal });
    } catch (err) {
      if (err.name === "AbortError") throw err;
      throw new ApiError("Could not reach the server. Check that it is running and try again.", 0, "network");
    }
    let data = null;
    const text = await response.text();
    if (text) { try { data = JSON.parse(text); } catch (e) { data = null; } }
    if (!response.ok) {
      const err = (data && data.error) || {};
      let message = err.message || (data && data.detail) || `Request failed (${response.status}).`;
      if (response.status === 403 && !err.message) message = "You do not have permission to do that.";
      if (response.status === 401) message = "Your session has expired. Please sign in again.";
      throw new ApiError(message, response.status, err.code || "error", err.details);
    }
    return data;
  };

  /* --------------------------------------------------------------------- Toasts */
  const ICONS = { success: "bi-check-circle-fill", danger: "bi-x-octagon-fill", error: "bi-x-octagon-fill", warning: "bi-exclamation-triangle-fill", info: "bi-info-circle-fill" };

  SS.toast = function (message, type = "info", { title, timeout = 5200 } = {}) {
    let stack = document.querySelector(".toast-stack");
    if (!stack) {
      stack = document.createElement("div");
      stack.className = "toast-stack";
      stack.setAttribute("aria-live", "polite");
      document.body.appendChild(stack);
    }
    const el = document.createElement("div");
    el.className = `ss-toast ${type}`;
    el.setAttribute("role", type === "danger" || type === "error" ? "alert" : "status");
    el.innerHTML = `<i class="bi ${ICONS[type] || ICONS.info} t-icon" aria-hidden="true"></i>
      <div class="min-w-0">${title ? `<div class="t-title"></div>` : ""}<div class="t-body"></div></div>
      <button type="button" class="t-close" aria-label="Dismiss"><i class="bi bi-x-lg"></i></button>`;
    if (title) el.querySelector(".t-title").textContent = title;
    el.querySelector(".t-body").textContent = message;
    const close = () => { el.classList.add("leaving"); setTimeout(() => el.remove(), 200); };
    el.querySelector(".t-close").addEventListener("click", close);
    stack.appendChild(el);
    if (timeout) setTimeout(close, timeout);
    return el;
  };

  /* ------------------------------------------------------------ Confirm dialog */
  /**
   * Promise-based confirmation modal. Resolves to {confirmed, value} where value is
   * the optional textarea content (e.g. a cancellation reason).
   */
  SS.confirm = function ({ title, message, confirmText = "Confirm", cancelText = "Go back", tone = "primary",
                           icon = "bi-question-lg", input = null, details = null } = {}) {
    return new Promise((resolve) => {
      const modalEl = document.getElementById("ssConfirmModal");
      const btnClass = { danger: "btn-danger", success: "btn-success", warning: "btn-navy", primary: "btn-primary" }[tone] || "btn-primary";
      modalEl.querySelector(".modal-icon").className = `modal-icon ${tone === "primary" ? "" : tone}`;
      modalEl.querySelector(".modal-icon i").className = `bi ${icon}`;
      modalEl.querySelector(".confirm-title").textContent = title || "Are you sure?";
      modalEl.querySelector(".confirm-message").textContent = message || "";
      const detailsEl = modalEl.querySelector(".confirm-details");
      detailsEl.innerHTML = "";
      detailsEl.hidden = !details;
      if (details) detailsEl.appendChild(details instanceof Node ? details : document.createRange().createContextualFragment(details));
      const inputWrap = modalEl.querySelector(".confirm-input-wrap");
      const textarea = inputWrap.querySelector("textarea");
      inputWrap.hidden = !input;
      textarea.value = "";
      if (input) { inputWrap.querySelector("label").textContent = input.label || "Note"; textarea.placeholder = input.placeholder || ""; }
      const ok = modalEl.querySelector(".confirm-ok");
      ok.className = `btn ${btnClass} confirm-ok`;
      ok.textContent = confirmText;
      modalEl.querySelector(".confirm-cancel").textContent = cancelText;
      const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
      let confirmed = false;
      const onOk = () => { confirmed = true; modal.hide(); };
      ok.addEventListener("click", onOk, { once: true });
      modalEl.addEventListener("hidden.bs.modal", () => {
        ok.removeEventListener("click", onOk);
        resolve({ confirmed, value: textarea.value.trim() });
      }, { once: true });
      modal.show();
      setTimeout(() => (input ? textarea : ok).focus(), 250);
    });
  };

  /* ------------------------------------------------------------- Button loading */
  SS.setLoading = function (btn, loading, label) {
    if (!btn) return;
    if (loading) {
      btn.dataset.originalHtml = btn.innerHTML;
      btn.disabled = true;
      btn.classList.add("is-loading");
      btn.innerHTML = `<span class="spinner-border" role="status" aria-hidden="true"></span><span>${label || "Working…"}</span>`;
    } else {
      btn.disabled = false;
      btn.classList.remove("is-loading");
      if (btn.dataset.originalHtml) btn.innerHTML = btn.dataset.originalHtml;
    }
  };

  SS.escape = function (s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  };

  SS.money = (n) => "₹" + Number(n || 0).toLocaleString("en-IN", { maximumFractionDigits: 0 });

  SS.initTooltips = function (root = document) {
    root.querySelectorAll('[data-bs-toggle="tooltip"]').forEach((el) => bootstrap.Tooltip.getOrCreateInstance(el));
  };

  /* ------------------------------------------------------- Coach seat layout */
  /**
   * Render a coach as bays (berth classes) or seat rows (chair classes).
   * coach = {number, kind: "berth"|"seat", bay_size}; seatFn(seat) returns a seat button's HTML.
   */
  SS.coachLayout = function (coach, seats, seatFn) {
    const size = coach.bay_size;
    const chunks = [];
    for (let i = 0; i < seats.length; i += size) chunks.push(seats.slice(i, i + size));
    let html = `<div class="coach-shell"><div class="coach-end">${SS.escape(coach.number)} · front</div>`;
    if (coach.kind === "berth") {
      const hasSide = size >= 6;
      const mainCount = hasSide ? size - 2 : size;
      const twoTier = mainCount === 4;
      chunks.forEach((bay) => {
        const main = bay.slice(0, mainCount);
        const side = hasSide ? bay.slice(mainCount) : [];
        html += `<div class="bay"><div class="bay-main ${twoTier ? "two-tier" : ""}">${main.map(seatFn).join("")}</div>`;
        if (side.length) html += `<div class="bay-side">${side.map(seatFn).join("")}</div>`;
        html += `</div>`;
      });
    } else {
      html += `<div class="chair-grid" style="--rows:${size + 1}">`;
      chunks.forEach((row) => {
        row.forEach((s, i) => { html += seatFn(s); if (i === 2) html += `<span class="aisle-gap"></span>`; });
        for (let k = row.length; k < size; k++) html += `<span class="aisle-gap"></span>`;
      });
      html += `</div>`;
    }
    return html + `<div class="coach-end">rear</div></div>`;
  };

  /* ---------------------------------------------------- Station autocomplete */
  function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

  SS.stationCombo = function (wrapper) {
    const input = wrapper.querySelector("input[type=text]");
    const hidden = wrapper.querySelector("input[type=hidden]");
    const list = wrapper.querySelector(".combo-list");
    let items = [];
    let active = -1;
    let controller = null;

    const render = () => {
      if (!items.length) { list.innerHTML = `<div class="combo-empty">No matching stations</div>`; return; }
      list.innerHTML = items.map((s, i) => `
        <div class="combo-option ${i === active ? "active" : ""}" role="option" data-i="${i}" aria-selected="${i === active}">
          <span class="code-pill">${SS.escape(s.code)}</span>
          <span class="min-w-0"><span class="name d-block">${SS.escape(s.name)}</span><span class="meta">${SS.escape(s.city)}, ${SS.escape(s.state)}</span></span>
        </div>`).join("");
    };
    const open = () => { list.classList.add("open"); input.setAttribute("aria-expanded", "true"); };
    const close = () => { list.classList.remove("open"); input.setAttribute("aria-expanded", "false"); active = -1; };
    const choose = (s) => {
      input.value = `${s.name} (${s.code})`;
      hidden.value = s.code;
      input.classList.remove("is-invalid");
      close();
      wrapper.dispatchEvent(new CustomEvent("station:selected", { bubbles: true, detail: s }));
    };
    const load = debounce(async (q) => {
      if (controller) controller.abort();
      controller = new AbortController();
      try {
        const data = await SS.api("/api/stations/", { params: { q }, signal: controller.signal });
        items = data.results; active = items.length ? 0 : -1; render(); open();
      } catch (e) { if (e.name !== "AbortError") { items = []; render(); } }
    }, 160);

    input.setAttribute("role", "combobox");
    input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("autocomplete", "off");
    input.addEventListener("input", () => { hidden.value = ""; load(input.value); });
    input.addEventListener("focus", () => { if (!hidden.value) load(input.value); else input.select(); });
    input.addEventListener("keydown", (e) => {
      if (!list.classList.contains("open")) return;
      if (e.key === "ArrowDown") { active = Math.min(active + 1, items.length - 1); render(); e.preventDefault(); }
      else if (e.key === "ArrowUp") { active = Math.max(active - 1, 0); render(); e.preventDefault(); }
      else if (e.key === "Enter" && active >= 0) { choose(items[active]); e.preventDefault(); }
      else if (e.key === "Escape") close();
    });
    list.addEventListener("mousedown", (e) => {
      const opt = e.target.closest(".combo-option");
      if (opt) { e.preventDefault(); choose(items[+opt.dataset.i]); }
    });
    input.addEventListener("blur", () => setTimeout(close, 120));
    return { set: choose };
  };

  /* ----------------------------------------------------- Train search form */
  function initSearchForms() {
    document.querySelectorAll("form[data-train-search]").forEach((form) => {
      const combos = Array.from(form.querySelectorAll(".station-combo")).map((w) => SS.stationCombo(w));
      const swap = form.querySelector("[data-swap]");
      if (swap) swap.addEventListener("click", () => {
        const [a, b] = form.querySelectorAll(".station-combo");
        const ia = a.querySelector("input[type=text]"), ib = b.querySelector("input[type=text]");
        const ha = a.querySelector("input[type=hidden]"), hb = b.querySelector("input[type=hidden]");
        [ia.value, ib.value] = [ib.value, ia.value];
        [ha.value, hb.value] = [hb.value, ha.value];
      });
      form.addEventListener("submit", (e) => {
        let ok = true;
        form.querySelectorAll(".station-combo").forEach((w) => {
          const hidden = w.querySelector("input[type=hidden]");
          const input = w.querySelector("input[type=text]");
          const fb = w.querySelector(".invalid-feedback");
          if (!hidden.value) { ok = false; input.classList.add("is-invalid"); if (fb) fb.textContent = "Choose a station from the list."; }
        });
        const [f, t] = form.querySelectorAll(".station-combo input[type=hidden]");
        if (ok && f.value === t.value) {
          ok = false;
          const input = form.querySelectorAll(".station-combo input[type=text]")[1];
          input.classList.add("is-invalid");
          const fb = form.querySelectorAll(".station-combo .invalid-feedback")[1];
          if (fb) fb.textContent = "Destination must differ from the origin.";
        }
        if (!ok) { e.preventDefault(); return; }
        const btn = form.querySelector("button[type=submit]");
        SS.setLoading(btn, true, "Searching…");
      });
      void combos;
    });
  }

  /* ---------------------------------------------------------- Sidebar toggle */
  function initSidebar() {
    const sidebar = document.querySelector(".app-sidebar");
    const backdrop = document.querySelector(".sidebar-backdrop");
    if (!sidebar) return;
    const toggle = (open) => { sidebar.classList.toggle("open", open); backdrop && backdrop.classList.toggle("open", open); };
    document.querySelectorAll("[data-sidebar-toggle]").forEach((b) => b.addEventListener("click", () => toggle(!sidebar.classList.contains("open"))));
    backdrop && backdrop.addEventListener("click", () => toggle(false));
  }

  /* ------------------------------------------------ Forms with confirmation */
  function initConfirmForms() {
    document.addEventListener("submit", async (e) => {
      const form = e.target;
      if (!form.matches("form[data-confirm]") || form.dataset.confirmed === "1") return;
      e.preventDefault();
      const { confirmed } = await SS.confirm({
        title: form.dataset.confirmTitle || "Please confirm",
        message: form.dataset.confirm,
        confirmText: form.dataset.confirmButton || "Confirm",
        tone: form.dataset.confirmTone || "primary",
        icon: form.dataset.confirmIcon || "bi-question-lg",
      });
      if (confirmed) {
        form.dataset.confirmed = "1";
        const btn = form.querySelector("[type=submit]");
        SS.setLoading(btn, true);
        form.submit();
      }
    });
    // Plain forms: show a spinner on submit to prevent double submission.
    document.addEventListener("submit", (e) => {
      const form = e.target;
      if (form.matches("form[data-confirm]") || form.matches("form[data-train-search]") || form.dataset.noLoading !== undefined) return;
      const btn = e.submitter || form.querySelector("[type=submit]");
      if (btn && form.checkValidity()) setTimeout(() => SS.setLoading(btn, true, btn.dataset.loadingText), 0);
    });
  }

  /* --------------------------------------------- Server messages as toasts */
  function flushServerMessages() {
    document.querySelectorAll("[data-server-message]").forEach((el) => {
      SS.toast(el.textContent.trim(), el.dataset.level || "info");
      el.remove();
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    initSidebar();
    initSearchForms();
    initConfirmForms();
    flushServerMessages();
    SS.initTooltips();
    document.querySelectorAll("[data-autosubmit]").forEach((el) => el.addEventListener("change", () => el.form.submit()));
    document.querySelectorAll("[data-print]").forEach((el) => el.addEventListener("click", () => window.print()));
  });
})();

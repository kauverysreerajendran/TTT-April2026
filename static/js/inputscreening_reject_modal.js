/* ============================================================================
 * Input Screening – Partial Reject Modal (manual scan flow).
 *
 * Fix-pack (Apr 2026) implements:
 *   1. Tap an active tray pill to fill the next empty scan slot
 *   2. Active tray pills are NOT repeated inside the delink section
 *   3. Tray-id input limited to 9 characters (maxlength)
 *   4. Auto-validate when length === 9; on success focus next empty slot,
 *      on failure mark input red + reselect text so user can retype
 *   5. Once scanned, the corresponding active-tray pill turns gray
 *   6. "Clear" button resets all user inputs (keeps lot context)
 *   7. "Save Draft" button persists scratch state to localStorage
 *   8. Body text is not bold (only headings/section titles are)
 *   9. Live "insight" chip in the header reports what the user is doing
 *      and the result of every validation
 *
 * Backend remains the single source of truth for every validation; the
 * front-end only renders state and forwards scans to /validate_scan/.
 * ============================================================================ */
(function () {
  "use strict";

  var TRAY_ID_LEN = 9;
  var DRAFT_KEY_PREFIX = "isrm_draft::";

  // ── Module state ──────────────────────────────────────────────────────────
  var state = {
    lotId: null,
    batchId: null,
    lotQty: 0,
    capacity: 0,
    trayType: null,
    activeTrays: [],
    reasons: [],
    rejectSlots: [],
    acceptSlots: [],
    rejectScans: [],
    acceptScans: [],
    delinkScans: [],    emptiedTrayIds: [],    counters: { reusable: 0, required: 0, delinkAvailable: 0 },
    previewTimer: null,
    isSubmitting: false,
    isPlanStale: false,
    scanEpoch: 0,
    fullLotReject: false,
  };

  // ── DOM helpers ───────────────────────────────────────────────────────────
  function $(id) { return document.getElementById(id); }
  function escHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  function getCsrf() {
    var v = null;
    if (document.cookie) {
      document.cookie.split(";").forEach(function (c) {
        var t = c.trim();
        if (t.indexOf("csrftoken=") === 0) {
          v = decodeURIComponent(t.substring("csrftoken=".length));
        }
      });
    }
    return v;
  }

  // ── Status / message helpers ──────────────────────────────────────────────
  function setStatus(kind, msg) {
    var el = $("isrm-status");
    if (!el) return;
    el.className = "isrm-status " + (kind || "info") + (msg ? " show" : "");
    el.textContent = msg || "";
  }
  function clearStatus() { setStatus("info", ""); }

  // ── Fix 9: Live insight chip ──────────────────────────────────────────────
  function setInsight(kind, msg) {
    var box = $("isrm-insight");
    var txt = $("isrm-insight-text");
    if (!box || !txt) return;
    box.className = "isrm-insight " + (kind || "info");
    txt.textContent = msg || "Idle";
    box.title = msg || "";
  }

  // ── Open / close ──────────────────────────────────────────────────────────
  function openModal(lotId, batchId) {
    state.lotId = lotId;
    state.batchId = batchId;
    resetUI();
    var modal = $("isRejectModal");
    if (modal) {
      // Clear the FOUC-blocking inline style applied in the template.
      modal.style.display = "";
      modal.classList.add("open");
    }
    setStatus("info", "Loading lot data…");
    setInsight("busy", "Loading lot data…");

    fetch("/inputscreening/reject_modal_context/?lot_id=" + encodeURIComponent(lotId), {
      credentials: "same-origin",
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data.success) {
          setStatus("error", data.error || "Failed to load lot data.");
          setInsight("error", "Failed to load lot.");
          return;
        }
        applyContext(data);
        loadDraftIfAny();
      })
      .catch(function () {
        setStatus("error", "Could not connect to server.");
        setInsight("error", "Network error.");
      });
  }

  function closeModal() {
    var modal = $("isRejectModal");
    if (modal) {
      modal.classList.remove("open");
      modal.style.display = "none";
    }
    clearTimeout(state.previewTimer);
  }

  function resetUI() {
    state.scanEpoch += 1;
    state.lotQty = 0; state.capacity = 0; state.trayType = null;
    state.activeTrays = []; state.reasons = [];
    state.rejectSlots = []; state.acceptSlots = [];
    state.rejectScans = []; state.acceptScans = []; state.delinkScans = [];
    state.emptiedTrayIds = [];
    state.counters = { reusable: 0, required: 0, delinkAvailable: 0 };
    state.isSubmitting = false;
    state.isPlanStale = false;

    ["isrm-h-lotqty", "isrm-tray-type", "isrm-capacity",
     "isrm-total-qty", "isrm-active-trays"
    ].forEach(function (id) { var e = $(id); if (e) e.textContent = "—"; });
    var rEl = $("isrm-total-reject"); if (rEl) rEl.textContent = "0";
    var aEl = $("isrm-total-accept"); if (aEl) aEl.textContent = "0";
    var rmEl = $("isrm-remarks"); if (rmEl) rmEl.value = "";
    var grid = $("isrm-reason-grid");
    if (grid) grid.innerHTML = "";
    $("isrm-reject-rows").innerHTML = '<div class="isrm-help-line" style="text-align:center;">Enter rejection quantities to begin</div>';
    $("isrm-accept-rows").innerHTML = '<div class="isrm-help-line" style="text-align:center;">Enter rejection quantities to begin</div>';
    $("isrm-delink-rows").innerHTML = "";
    var _ccReset = $("isrm-calc-card"); if (_ccReset) _ccReset.style.display = "none";
    var _crReset = $("isrm-calc-rule"); if (_crReset) _crReset.style.display = "none";
    $("isrm-sec-delink").style.display = "none";
    $("isrm-sec-alloc").classList.add("isrm-locked");
    $("isrm-sec-delink").classList.add("isrm-locked");
    $("isrm-submit-btn").disabled = true;
    $("isrm-reject-count").textContent = "0";
    $("isrm-accept-count").textContent = "0";
    var lotRej = $("isrm-lot-reject-toggle"); if (lotRej) lotRej.checked = false;
    state.fullLotReject = false;
    var _bodyReset = document.querySelector("#isRejectModal .isrm-body");
    if (_bodyReset) _bodyReset.classList.remove("isrm-full-reject-mode");
    var _submitReset = $("isrm-submit-btn");
    if (_submitReset) _submitReset.textContent = "Submit";
    setInsight("info", "Idle");
  }

  // ── Apply initial context ────────────────
  function applyContext(data) {
    state.lotQty = data.lot_qty || 0;
    state.capacity = data.tray_capacity || 0;
    state.trayType = data.tray_type || null;
    state.activeTrays = data.active_trays || [];
    state.reasons = data.rejection_reasons || [];

    $("isrm-h-batch").textContent = data.plating_stk_no || "—";
    $("isrm-h-lotqty").textContent = state.lotQty;
    $("isrm-tray-type").textContent = state.trayType || "—";
    $("isrm-capacity").textContent = state.capacity || "—";
    $("isrm-total-qty").textContent = state.lotQty;
    $("isrm-active-trays").textContent = state.activeTrays.length;

    renderActivePills();
    renderReasonGrid();
    clearStatus();
    setInsight("info", "Ready. Enter rejection qty.");
  }

  // ── Fix 5: track which active-tray pills are in use ──────────────────────
  function usedActiveIds() {
    var s = new Set();
    state.rejectScans.forEach(function (x) { if (x) s.add((x.tray_id || "").toUpperCase()); });
    state.acceptScans.forEach(function (x) { if (x) s.add((x.tray_id || "").toUpperCase()); });
    state.delinkScans.forEach(function (x) { if (x) s.add((x.tray_id || "").toUpperCase()); });
    return s;
  }

  // ── Render active tray pills (Fix 1: tap-to-pick, Fix 5: gray when used) ─
  function renderActivePills() {
    var c = $("isrm-active-pills");
    if (!c) return;
    if (!state.activeTrays.length) {
      c.innerHTML = '<span class="isrm-help-line">No active trays found</span>';
      return;
    }
    var used = usedActiveIds();
    c.innerHTML = state.activeTrays.map(function (t) {
      var isUsed = used.has((t.tray_id || "").toUpperCase());
      return '<span class="isrm-pill ' + (isUsed ? "used" : "") + '" ' +
        'data-tray-id="' + escHtml(t.tray_id) + '" ' +
        'title="' + (isUsed ? "Already used" : "Tap to pick") + '">' +
        escHtml(t.tray_id) +
        (t.top_tray ? '<span class="isrm-pill-top">TOP</span>' : '') +
        '<span class="isrm-pill-qty">' + (t.qty != null ? t.qty : "?") + '</span>' +
        '</span>';
    }).join("");

    c.querySelectorAll(".isrm-pill").forEach(function (pill) {
      pill.addEventListener("click", function () {
        if (this.classList.contains("used")) return;
        var trayId = (this.getAttribute("data-tray-id") || "").toUpperCase();
        pickIntoNextEmptySlot(trayId);
      });
    });
  }

  // ── Render reason input grid ──────────────────────────────────────────────
  function renderReasonGrid() {
    var grid = $("isrm-reason-grid");
    if (!grid) return;
    if (!state.reasons.length) {
      grid.innerHTML = '<div class="isrm-help-line" style="grid-column:1/-1;text-align:center;">No rejection reasons configured</div>';
      return;
    }
    grid.innerHTML = state.reasons.map(function (r) {
      return '<div class="isrm-reason-row">' +
        '<span class="isrm-reason-id">' + escHtml(r.rejection_reason_id) + '</span>' +
        '<span class="isrm-reason-text">' + escHtml(r.rejection_reason) + '</span>' +
        '<input type="number" min="0" max="' + state.lotQty + '" value="0" ' +
        'class="isrm-qty-input" data-reason-id="' + escHtml(r.rejection_reason_id) +
        '" data-reason-text="' + escHtml(r.rejection_reason) + '" />' +
        '</div>';
    }).join("");

    grid.querySelectorAll(".isrm-qty-input").forEach(function (inp) {
      inp.addEventListener("input", function () {
        clampQty(this);
        updateTotals();
        scheduleSlotPlan();
        setInsight("busy", "Updating allocation…");
      });
    });
  }

  function clampQty(input) {
    var v = parseInt(input.value, 10) || 0;
    if (v < 0) v = 0;
    if (state.lotQty > 0 && v > state.lotQty) v = state.lotQty;
    var others = collectRejectionEntries()
      .filter(function (e) { return e.reason_id !== input.getAttribute("data-reason-id"); })
      .reduce(function (s, e) { return s + e.qty; }, 0);
    var max = state.lotQty - others;
    if (v > max) v = Math.max(0, max);
    input.value = v;
  }

  function collectRejectionEntries() {
    var out = [];
    var grid = $("isrm-reason-grid");
    if (!grid) return out;
    grid.querySelectorAll(".isrm-qty-input").forEach(function (inp) {
      var qty = parseInt(inp.value, 10) || 0;
      if (qty > 0) {
        out.push({
          reason_id: inp.getAttribute("data-reason-id"),
          reason_text: inp.getAttribute("data-reason-text"),
          qty: qty,
        });
      }
    });
    return out;
  }

  function totalReject() {
    return collectRejectionEntries().reduce(function (s, e) { return s + e.qty; }, 0);
  }

  function updateTotals() {
    var tr = totalReject();
    $("isrm-total-reject").textContent = tr;
    $("isrm-total-accept").textContent = Math.max(0, state.lotQty - tr);
  }

  // ── Slot plan from backend ────────────────────────────────────────────────
  function scheduleSlotPlan() {
    state.isPlanStale = true;
    updateSubmitState();
    clearTimeout(state.previewTimer);
    state.previewTimer = setTimeout(fetchSlotPlan, 350);
  }

  function fetchSlotPlan() {
    var entries = collectRejectionEntries();
    var tr = entries.reduce(function (s, e) { return s + e.qty; }, 0);
    if (tr <= 0) {
      state.rejectSlots = []; state.acceptSlots = [];
      state.rejectScans = []; state.acceptScans = []; state.delinkScans = [];
      var _ccF = $('isrm-calc-card'); if (_ccF) _ccF.style.display = 'none';
      var _crF = $('isrm-calc-rule'); if (_crF) _crF.style.display = 'none';
      $("isrm-sec-alloc").classList.add("isrm-locked");
      $("isrm-sec-delink").style.display = "none";
      $("isrm-reject-rows").innerHTML = '<div class="isrm-help-line" style="text-align:center;">Enter rejection quantities to begin</div>';
      $("isrm-accept-rows").innerHTML = '<div class="isrm-help-line" style="text-align:center;">Enter rejection quantities to begin</div>';
      $("isrm-reject-count").textContent = "0";
      $("isrm-accept-count").textContent = "0";
      renderActivePills();
      updateSubmitState();
      setInsight("info", "Ready. Enter rejection qty.");
      return;
    }
    if (tr >= state.lotQty) {
      setStatus("error", "Reject qty must be less than lot qty (" + state.lotQty + ").");
      setInsight("error", "Reject qty too high.");
      return;
    }

    fetch("/inputscreening/allocation_preview/", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": getCsrf() },
      body: JSON.stringify({
        lot_id: state.lotId,
        rejection_entries: entries,
        delink_count: 0,
      }),
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        applySlotPlan(data);
        setInsight("info", "Allocation ready. Scan reject trays.");
      })
      .catch(function () {
        setStatus("error", "Could not fetch slot plan.");
        setInsight("error", "Network error fetching plan.");
      });
  }

  function applySlotPlan(data) {
    state.isPlanStale = false;
    state.rejectSlots = data.reject_slots || [];
    state.acceptSlots = data.accept_slots || [];
    state.emptiedTrayIds = (data.emptied_tray_ids || []).map(function (t) {
      return (t || "").toUpperCase();
    });
    state.counters = {
      reusable: data.reusable_count || 0,
      required: data.new_required || 0,
      delinkAvailable: data.delink_available || 0,
    };

    state.rejectScans = state.rejectSlots.map(function (_, i) {
      return state.rejectScans[i] || null;
    });
    state.acceptScans = state.acceptSlots.map(function (_, i) {
      return state.acceptScans[i] || null;
    });
    var activeIds = new Set(state.activeTrays.map(function (t) {
      return (t.tray_id || "").toUpperCase();
    }));
    state.delinkScans = state.delinkScans.filter(function (d) {
      return activeIds.has((d.tray_id || "").toUpperCase());
    });

    $("isrm-c-reusable").textContent = state.counters.reusable;
    $("isrm-c-required").textContent = state.counters.required;
    $("isrm-c-delink").textContent = state.counters.delinkAvailable;
    // Update calc card inside Step 1
    var calcCard = $('isrm-calc-card');
    var calcRule = $('isrm-calc-rule');
    if (calcCard) {
      var acceptQtyEl = $('isrm-calc-accept-qty');
      var lotQtyEl = $('isrm-calc-lot-qty');
      if (acceptQtyEl) acceptQtyEl.textContent = data.total_accept_qty != null ? data.total_accept_qty : '—';
      if (lotQtyEl) lotQtyEl.textContent = state.lotQty;
      calcCard.style.display = 'flex';
    }
    if (calcRule) calcRule.style.display = '';

    $("isrm-reject-count").textContent = state.rejectSlots.length;
    $("isrm-accept-count").textContent = state.acceptSlots.length;

    $("isrm-sec-alloc").classList.remove("isrm-locked");
    $("isrm-sec-delink").style.display = state.counters.delinkAvailable > 0 ? "" : "none";

    renderRejectRows();
    renderAcceptRows();
    renderDelinkSection();
    renderActivePills();
    updateSubmitState();
    clearStatus();
  }

  // ── Render reject rows (Section 2 left) ───────────────────────────────────
  function renderRejectRows() {
    var c = $("isrm-reject-rows");
    if (!state.rejectSlots.length) {
      c.innerHTML = '<div class="isrm-help-line" style="text-align:center;">No reject slots</div>';
      return;
    }
    c.innerHTML = state.rejectSlots.map(function (slot, i) {
      var scan = state.rejectScans[i];
      var filled = !!scan;
      var sourceBadge = "";
      if (filled) {
        sourceBadge = scan.source === "new"
          ? '<span class="isrm-badge new">NEW</span>'
          : '<span class="isrm-badge reused">REUSED</span>';
      }
      return '<div class="isrm-alloc-row ' + (filled ? "filled" : "") + '" data-slot-idx="' + i + '">' +
        '<span class="isrm-alloc-num">' + (i + 1) + '</span>' +
        '<input type="text" class="isrm-scan-input isrm-reject-scan" ' +
          'data-slot-idx="' + i + '" maxlength="' + TRAY_ID_LEN + '" autocomplete="off" ' +
          'placeholder="SCAN / TAP REJECT TRAY" ' +
          'value="' + escHtml(filled ? scan.tray_id : "") + '" ' +
          (filled ? "readonly" : "") + ' />' +
        '<button type="button" class="isrm-row-clear isrm-reject-clear" data-slot-idx="' + i + '" ' +
          (filled ? "" : "disabled") + ' title="Clear">&times;</button>' +
        '<span class="isrm-badge reason">' + escHtml(slot.reason_id) + '</span>' +
        '<span class="isrm-alloc-qty">' + slot.qty + '</span>' +
        sourceBadge +
        '</div>';
    }).join("");

    c.querySelectorAll(".isrm-reject-scan").forEach(function (inp) {
      if (!inp.readOnly) {
        attachScanHandlers(inp, "reject");
      }
    });
    // Err2 fix: tap a filled (readonly) reject input to clear & re-scan
    c.querySelectorAll(".isrm-reject-scan[readonly]").forEach(function (inp) {
      inp.addEventListener("click", function () {
        var idx = parseInt(this.getAttribute("data-slot-idx"), 10);
        state.rejectScans[idx] = null;
        renderRejectRows();
        renderActivePills();
        renderDelinkSection();
        updateSubmitState();
        setInsight("info", "Cleared reject slot " + (idx + 1) + ". Re-scan.");
      });
    });
    c.querySelectorAll(".isrm-reject-clear").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var idx = parseInt(this.getAttribute("data-slot-idx"), 10);
        state.rejectScans[idx] = null;
        renderRejectRows();
        renderActivePills();
        renderDelinkSection();
        updateSubmitState();
        setInsight("info", "Cleared reject slot " + (idx + 1) + ".");
      });
    });
  }

  // ── Render accept rows (Section 2 right) ──────────────────────────────────
  function renderAcceptRows() {
    var c = $("isrm-accept-rows");
    if (!state.acceptSlots.length) {
      c.innerHTML = '<div class="isrm-help-line" style="text-align:center;">No accept slots</div>';
      return;
    }
    c.innerHTML = state.acceptSlots.map(function (slot, i) {
      var scan = state.acceptScans[i];
      var filled = !!scan;
      var sourceBadge = "";
      var topBadge = "";
      if (filled) {
        sourceBadge = scan.source === "free"
          ? '<span class="isrm-badge new">FREE</span>'
          : '<span class="isrm-badge existing">EXISTING</span>';
        if (scan.top) topBadge = '<span class="isrm-badge top">TOP</span>';
      }
      return '<div class="isrm-alloc-row ' + (filled ? "filled" : "") + '" data-slot-idx="' + i + '">' +
        '<span class="isrm-alloc-num">' + (i + 1) + '</span>' +
        '<input type="text" class="isrm-scan-input isrm-accept-scan" ' +
          'data-slot-idx="' + i + '" maxlength="' + TRAY_ID_LEN + '" autocomplete="off" ' +
          'placeholder="SCAN / TAP ACCEPT TRAY" ' +
          'value="' + escHtml(filled ? scan.tray_id : "") + '" ' +
          (filled ? "readonly" : (rejectStepDone() ? "" : "disabled")) + ' />' +
        '<button type="button" class="isrm-row-clear isrm-accept-clear" data-slot-idx="' + i + '" ' +
          (filled ? "" : "disabled") + ' title="Clear">&times;</button>' +
        topBadge +
        '<span class="isrm-alloc-qty">' + slot.qty + '</span>' +
        sourceBadge +
        '</div>';
    }).join("");

    c.querySelectorAll(".isrm-accept-scan").forEach(function (inp) {
      if (!inp.readOnly) {
        attachScanHandlers(inp, "accept");
      }
    });
    // Err2 fix: tap a filled (readonly) accept input to clear & re-scan
    c.querySelectorAll(".isrm-accept-scan[readonly]").forEach(function (inp) {
      inp.addEventListener("click", function () {
        var idx = parseInt(this.getAttribute("data-slot-idx"), 10);
        state.acceptScans[idx] = null;
        renderAcceptRows();
        renderActivePills();
        updateSubmitState();
        setInsight("info", "Cleared accept slot " + (idx + 1) + ". Re-scan.");
      });
    });
    c.querySelectorAll(".isrm-accept-clear").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var idx = parseInt(this.getAttribute("data-slot-idx"), 10);
        state.acceptScans[idx] = null;
        renderAcceptRows();
        renderActivePills();
        updateSubmitState();
        setInsight("info", "Cleared accept slot " + (idx + 1) + ".");
      });
    });
  }

  // ── Render delink section (Fix 2: no duplicate active-tray pills) ────────
  function renderDelinkSection() {
    var rows = $("isrm-delink-rows");
    if (!rows) return;

    // Remaining delink slots = emptied count − active trays already reused
    // in reject scans. Once reject fully consumes the emptied pool there
    // is nothing left to delink, so the whole section hides.
    var activeIds = new Set((state.activeTrays || []).map(function (t) {
      return (t.tray_id || "").toUpperCase();
    }));
    var reusedInReject = state.rejectScans.filter(function (s) {
      return s && activeIds.has((s.tray_id || "").toUpperCase());
    }).length;
    var remainingDelink = Math.max(
      0,
      (state.counters.delinkAvailable || 0) - reusedInReject
    );

    // Drop any already-scanned delink rows that no longer fit inside the
    // shrunken pool (e.g. the user just reused one more emptied tray).
    if (state.delinkScans.length > remainingDelink) {
      state.delinkScans = state.delinkScans.slice(0, remainingDelink);
    }

    if (remainingDelink <= 0 && state.delinkScans.length === 0) {
      $("isrm-sec-delink").style.display = "none";
      rows.innerHTML = "";
      return;
    }
    $("isrm-sec-delink").style.display = "";
    $("isrm-sec-delink").classList.toggle("isrm-locked", !rejectStepDone());

    var html = state.delinkScans.map(function (d, i) {
      return '<div class="isrm-delink-row" style="margin-bottom:6px;">' +
        '<span class="isrm-alloc-num">' + (i + 1) + '</span>' +
        '<input type="text" class="isrm-scan-input" value="' + escHtml(d.tray_id) + '" readonly />' +
        '<button type="button" class="isrm-row-clear isrm-delink-clear" data-idx="' + i + '" title="Remove">&times;</button>' +
        '</div>';
    }).join("");

    if (state.delinkScans.length < remainingDelink) {
      var nextIdx = state.delinkScans.length + 1;
      var disabled = !rejectStepDone();
      html += '<div class="isrm-delink-row">' +
        '<span class="isrm-alloc-num">' + nextIdx + '</span>' +
        '<input type="text" class="isrm-scan-input isrm-delink-scan" ' +
          'maxlength="' + TRAY_ID_LEN + '" autocomplete="off" ' +
          'placeholder="SCAN / TAP DELINK TRAY" ' + (disabled ? "disabled" : "") + ' />' +
        '<button type="button" class="isrm-row-clear" disabled>&times;</button>' +
        '</div>';
    }
    rows.innerHTML = html;

    var newInput = rows.querySelector(".isrm-delink-scan");
    if (newInput) attachScanHandlers(newInput, "delink");

    rows.querySelectorAll(".isrm-delink-clear").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var i = parseInt(this.getAttribute("data-idx"), 10);
        state.delinkScans.splice(i, 1);
        renderDelinkSection();
        renderActivePills();
        updateSubmitState();
        setInsight("info", "Removed delink entry.");
      });
    });
  }

  // ── Fix 1 & 4: Unified scan input behaviour ──────────────────────────────
  function attachScanHandlers(input, slotType) {
    input.addEventListener("input", function () {
      this.value = (this.value || "").toUpperCase();
      this.classList.remove("invalid");
      var v = this.value.trim();
      if (v.length > 0 && v.length < TRAY_ID_LEN) {
        setInsight("busy", "Typing " + slotType + " tray (" + v.length + "/" + TRAY_ID_LEN + ")…");
      }
      // Fix 4: auto-validate as soon as the 9th char is entered
      if (v.length === TRAY_ID_LEN) {
        attemptScan(this, slotType, v);
      }
    });
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        e.preventDefault();
        var v = (this.value || "").trim().toUpperCase();
        if (v) attemptScan(this, slotType, v);
      }
    });
    input.addEventListener("blur", function () {
      var v = (this.value || "").trim().toUpperCase();
      if (v && v.length === TRAY_ID_LEN && !this.readOnly) attemptScan(this, slotType, v);
    });
  }

  function attemptScan(input, slotType, trayId) {
    if (slotType === "accept" && !rejectStepDone()) {
      setStatus("error", "Please complete reject scans first.");
      setInsight("error", "Reject scans incomplete.");
      input.value = ""; input.classList.add("invalid");
      return;
    }
    if (slotType === "delink" && !rejectStepDone()) {
      setStatus("error", "Please complete reject scans first.");
      setInsight("error", "Reject scans incomplete.");
      input.value = ""; input.classList.add("invalid");
      return;
    }
    setInsight("busy", "Validating " + trayId + " (" + slotType + ")…");
    input.disabled = true;
    var capturedEpoch = state.scanEpoch;
    validateScan(slotType, trayId, function (res) {
      input.disabled = false;
      if (state.scanEpoch !== capturedEpoch) return;
      if (!res.valid) {
        setStatus("error", res.reason || "Invalid tray.");
        setInsight("error", trayId + " invalid: " + (res.reason || "rejected"));
        // Fix 4: keep selection on the invalid input so user can retype
        input.classList.add("invalid");
        input.focus();
        try { input.setSelectionRange(0, input.value.length); } catch (e) {}
        return;
      }
      handleValidScan(slotType, input, res);
    });
  }

  function handleValidScan(slotType, input, res) {
    if (slotType === "reject") {
      var idx = parseInt(input.getAttribute("data-slot-idx"), 10);
      state.rejectScans[idx] = {
        tray_id: res.tray_id, source: res.source,
        qty: res.tray_qty, top: res.top_tray,
      };
      renderRejectRows();
      renderActivePills();
      renderDelinkSection();
      // Re-render accept rows so inputs become enabled once reject step is complete.
      // Do NOT auto-fill here — user must manually scan the top tray (slot 1) first.
      renderAcceptRows();
      setInsight("success", res.tray_id + " accepted as REJECT (" + res.source + ").");
    } else if (slotType === "accept") {
      var aidx = parseInt(input.getAttribute("data-slot-idx"), 10);
      state.acceptScans[aidx] = {
        tray_id: res.tray_id, source: res.source,
        qty: res.tray_qty, top: res.top_tray,
      };
      renderAcceptRows();
      renderActivePills();
      autoFillRemainingAcceptSlots();
      setInsight("success", res.tray_id + " accepted as ACCEPT (" + res.source + ").");
    } else if (slotType === "delink") {
      state.delinkScans.push({
        tray_id: res.tray_id, qty: res.tray_qty, top: res.top_tray,
      });
      renderDelinkSection();
      renderActivePills();
      setInsight("success", res.tray_id + " queued for DELINK.");
    }
    clearStatus();
    updateSubmitState();
    // Fix 4: focus the next empty scan slot after a successful scan
    focusNextEmptySlot(slotType);
  }

  function focusNextEmptySlot(slotType) {
    var selectors;
    if (slotType === "reject") {
      selectors = [".isrm-reject-scan", ".isrm-delink-scan", ".isrm-accept-scan"];
    } else if (slotType === "delink") {
      selectors = [".isrm-delink-scan", ".isrm-accept-scan"];
    } else {
      selectors = [".isrm-accept-scan"];
    }
    for (var i = 0; i < selectors.length; i++) {
      var nodes = document.querySelectorAll(selectors[i]);
      for (var j = 0; j < nodes.length; j++) {
        var n = nodes[j];
        if (!n.readOnly && !n.disabled && !n.value) { n.focus(); return; }
      }
    }
  }

  // ── Fix 1: Tap an active-tray pill → fill next empty slot ────────────────
  function pickIntoNextEmptySlot(trayId) {
    // Order: reject → delink (if available) → accept
    // Err3 fix: use the same remainingDelink formula as renderDelinkSection so
    // that active trays already reused in reject scans reduce the delink pool,
    // preventing an infinite loop where delinkNeeded stays true after scanning.
    var _activeIds = new Set((state.activeTrays || []).map(function (t) {
      return (t.tray_id || "").toUpperCase();
    }));
    var _reusedInReject = state.rejectScans.filter(function (s) {
      return s && _activeIds.has((s.tray_id || "").toUpperCase());
    }).length;
    var _remainingDelink = Math.max(0, (state.counters.delinkAvailable || 0) - _reusedInReject);
    var delinkNeeded = _remainingDelink > 0 && state.delinkScans.length < _remainingDelink;
    var slotType = !rejectStepDone() ? "reject"
                 : delinkNeeded ? "delink"
                 : (state.acceptSlots.length && !acceptStepDone()) ? "accept"
                 : null;
    if (!slotType) {
      setInsight("error", "No empty slot available to fill.");
      return;
    }
    var sel = slotType === "reject" ? ".isrm-reject-scan"
            : slotType === "accept" ? ".isrm-accept-scan"
            : ".isrm-delink-scan";
    var nodes = document.querySelectorAll(sel);
    for (var i = 0; i < nodes.length; i++) {
      var n = nodes[i];
      if (!n.readOnly && !n.disabled && !n.value) {
        n.value = trayId;
        attemptScan(n, slotType, trayId);
        return;
      }
    }
    setInsight("error", "No empty " + slotType + " slot.");
  }

  // ── Auto-fill remaining accept slots (slots 1+) from unused active trays ────
  // Slot 0 is reserved for the top/partial tray which the user must scan first.
  // Once slot 0 is confirmed, this function cascades through slots 1+ in order,
  // filling each from unused active trays sorted ascending by qty.
  function autoFillRemainingAcceptSlots() {
    // Guard: do nothing until the user has confirmed the top-tray slot (slot 0).
    if (!state.acceptScans.length || state.acceptScans[0] === null) return;

    var used = new Set(collectAllUsedIds().map(function (id) { return id.toUpperCase(); }));
    // Sort unused active trays ascending by qty so smaller trays fill first.
    var unusedActive = state.activeTrays.filter(function (t) {
      return !used.has((t.tray_id || "").toUpperCase());
    }).sort(function (a, b) { return (a.qty || 0) - (b.qty || 0); });

    if (!unusedActive.length) return;

    // Only target empty slots at index >= 1 (leave slot 0 to user).
    var emptyInputs = Array.prototype.slice.call(
      document.querySelectorAll(".isrm-accept-scan")
    ).filter(function (n) {
      return !n.readOnly && !n.disabled && !n.value &&
             parseInt(n.getAttribute("data-slot-idx"), 10) >= 1;
    });
    if (!emptyInputs.length) return;
    var inp = emptyInputs[0];
    var trayId = unusedActive[0].tray_id.toUpperCase();
    inp.value = trayId;
    attemptScan(inp, "accept", trayId);
  }

  // ── Validate scan API ─────────────────────────────────────────────────────
  function validateScan(slotType, trayId, cb) {
    var used = collectAllUsedIds();
    fetch("/inputscreening/validate_scan/", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": getCsrf() },
      body: JSON.stringify({
        lot_id: state.lotId,
        slot_type: slotType,
        tray_id: trayId,
        used_tray_ids: used,
        reject_qty: totalReject(),
      }),
    })
      .then(function (r) { return r.json(); })
      .then(cb)
      .catch(function () { cb({ valid: false, reason: "Network error during scan." }); });
  }

  function collectAllUsedIds() {
    var ids = [];
    state.rejectScans.forEach(function (s) { if (s) ids.push(s.tray_id); });
    state.acceptScans.forEach(function (s) { if (s) ids.push(s.tray_id); });
    state.delinkScans.forEach(function (s) { if (s) ids.push(s.tray_id); });
    return ids;
  }

  // ── Step gating helpers ──────────────────────────────────────────────────
  function rejectStepDone() {
    if (!state.rejectSlots.length) return false;
    return state.rejectScans.length === state.rejectSlots.length &&
           state.rejectScans.every(Boolean);
  }
  function acceptStepDone() {
    if (!state.acceptSlots.length) return true;
    return state.acceptScans.length === state.acceptSlots.length &&
           state.acceptScans.every(Boolean);
  }

  function updateSubmitState() {
    var ok = totalReject() > 0 &&
             totalReject() < state.lotQty &&
             !state.isPlanStale &&
             rejectStepDone() &&
             acceptStepDone() &&
             !state.isSubmitting;
    $("isrm-submit-btn").disabled = !ok;

    if (state.acceptSlots.length) {
      var anyDisabled = !rejectStepDone();
      $("isrm-accept-rows").querySelectorAll(".isrm-accept-scan").forEach(function (inp) {
        if (!inp.readOnly) inp.disabled = anyDisabled;
      });
    }
    var delinkInput = $("isrm-delink-rows").querySelector(".isrm-delink-scan");
    if (delinkInput && !delinkInput.readOnly) {
      delinkInput.disabled = !rejectStepDone();
    }
    $("isrm-sec-delink").classList.toggle("isrm-locked", !rejectStepDone());
  }

  // ── Fix 6: Clear all user inputs (keep lot context) ──────────────────────
  function clearAllInputs() {
    state.scanEpoch += 1;  // invalidate any in-flight scan callbacks
    var grid = $("isrm-reason-grid");
    if (grid) {
      grid.querySelectorAll(".isrm-qty-input").forEach(function (i) { i.value = 0; });
    }
    state.rejectScans = state.rejectSlots.map(function () { return null; });
    state.acceptScans = state.acceptSlots.map(function () { return null; });
    state.delinkScans = [];
    var rmEl = $("isrm-remarks"); if (rmEl) rmEl.value = "";
    var lotRej = $("isrm-lot-reject-toggle"); if (lotRej) lotRej.checked = false;
    // Immediately re-render rows so DOM clears without waiting for the async slot plan.
    renderRejectRows();
    renderAcceptRows();
    renderDelinkSection();
    updateTotals();
    scheduleSlotPlan();
    renderActivePills();
    setInsight("info", "All inputs cleared.");
  }

  // ── Fix 7: Save / load draft via localStorage ────────────────────────────
  function draftKey() { return DRAFT_KEY_PREFIX + (state.lotId || ""); }

  function saveDraft() {
    if (!state.lotId) return;
    var entries = collectRejectionEntries();
    var payload = {
      lot_id: state.lotId,
      rejection_entries: entries,
      reject_assignments: state.rejectSlots.map(function (slot, i) {
        var s = state.rejectScans[i];
        return s ? { tray_id: s.tray_id, reason_id: slot.reason_id } : null;
      }).filter(Boolean),
      accept_assignments: state.acceptSlots.map(function (_, i) {
        var s = state.acceptScans[i];
        return s ? { tray_id: s.tray_id } : null;
      }).filter(Boolean),
      delink_tray_ids: (state.delinkScans || []).map(function (d) { return d.tray_id; }),
      remarks: ($("isrm-remarks") || {}).value || "",
    };

    // Local fallback – retained so UI state is recoverable if the network
    // request fails before the backend acknowledges the draft.
    try {
      window.localStorage.setItem(draftKey(), JSON.stringify({
        ts: Date.now(),
        reasons: entries,
        rejectScans: state.rejectScans,
        acceptScans: state.acceptScans,
        delinkScans: state.delinkScans,
        remarks: payload.remarks,
      }));
    } catch (e) { /* storage full – ignore, backend is SSOT */ }

    var draftBtn = $("isrm-draft-btn");
    if (draftBtn) { draftBtn.disabled = true; draftBtn.textContent = "Saving…"; }
    setInsight("busy", "Saving draft…");

    fetch("/inputscreening/save_draft/", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": getCsrf() },
      body: JSON.stringify(payload),
    })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, data: j }; }); })
      .then(function (resp) {
        if (draftBtn) { draftBtn.disabled = false; draftBtn.textContent = "Save Draft"; }
        if (!resp.ok || !resp.data.success) {
          setInsight("error", (resp.data && resp.data.error) || "Draft save failed.");
          return;
        }
        setInsight("success", "Draft saved.");
      })
      .catch(function () {
        if (draftBtn) { draftBtn.disabled = false; draftBtn.textContent = "Save Draft"; }
        setInsight("error", "Network error – draft stored locally only.");
      });
  }

  function loadDraftIfAny() {
    if (!state.lotId) return;
    var raw = null;
    try { raw = window.localStorage.getItem(draftKey()); } catch (e) {}
    if (!raw) return;
    var data;
    try { data = JSON.parse(raw); } catch (e) { return; }
    if (!data || !data.reasons) return;
    // Restore qtys
    var grid = $("isrm-reason-grid");
    if (grid && data.reasons.length) {
      var byId = {};
      data.reasons.forEach(function (r) { byId[r.reason_id] = r.qty; });
      grid.querySelectorAll(".isrm-qty-input").forEach(function (inp) {
        var id = inp.getAttribute("data-reason-id");
        if (byId[id] != null) inp.value = byId[id];
      });
    }
    // Stash scans so applySlotPlan picks them back up by index
    state.rejectScans = (data.rejectScans || []).slice();
    state.acceptScans = (data.acceptScans || []).slice();
    state.delinkScans = (data.delinkScans || []).slice();
    var rmEl = $("isrm-remarks");
    if (rmEl && data.remarks) rmEl.value = data.remarks;
    updateTotals();
    scheduleSlotPlan();
    setInsight("info", "Draft restored.");
  }

  function clearDraft() {
    try { window.localStorage.removeItem(draftKey()); } catch (e) {}
  }

  // ── Submit ────────────────────────────────────────────────────────────────
  function submit() {
    if (state.isSubmitting) return;

    // ── FULL LOT REJECT shortcut ────────────────────────────────────────
    // When the operator ticks "Lot Rejection" in the header, skip the
    // partial allocation flow entirely and POST to the dedicated full
    // reject endpoint. Remarks are mandatory in this mode.
    if (state.fullLotReject) {
      var rmEl = $("isrm-remarks");
      var rmText = ((rmEl && rmEl.value) || "").trim();
      if (!rmText) {
        setStatus("error", "Lot Rejection remarks are required.");
        setInsight("error", "Remarks required.");
        if (rmEl) rmEl.focus();
        return;
      }
      state.isSubmitting = true;
      var fbtn = $("isrm-submit-btn");
      if (fbtn) { fbtn.disabled = true; fbtn.textContent = "Submitting\u2026"; }
      setStatus("info", "Submitting full lot rejection\u2026");
      setInsight("busy", "Submitting\u2026");
      // mark S circle as scanning-WIP (half-green) ──────────────────
      if (typeof window.isMarkSCircleWip === "function") {
        window.isMarkSCircleWip(state.lotId);
      }
      fetch("/inputscreening/full_reject/", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": getCsrf() },
        body: JSON.stringify({ lot_id: state.lotId, remarks: rmText }),
      })
        .then(function (r) {
          return r.json().then(function (j) { return { ok: r.ok, data: j }; });
        })
        .then(function (resp) {
          state.isSubmitting = false;
          if (fbtn) fbtn.textContent = "Submit";
          if (!resp.ok || !resp.data.success) {
            setStatus("error", (resp.data && resp.data.error) || "Full reject failed.");
            setInsight("error", "Submit failed.");
            if (fbtn) fbtn.disabled = false;
            return;
          }
          clearDraft();
          setStatus("success", "Lot rejected.");
          setInsight("success", "Submitted.");
          if (typeof Swal !== "undefined") {
            Swal.fire({
              icon: "success",
              title: "Lot Rejected",
              text: "Rejected qty: " + resp.data.rejected_qty,
              timer: 1800,
              showConfirmButton: false,
            }).then(function () { closeModal(); location.reload(); });
          } else {
            setTimeout(function () { closeModal(); location.reload(); }, 800);
          }
        })
        .catch(function () {
          state.isSubmitting = false;
          if (fbtn) { fbtn.disabled = false; fbtn.textContent = "Submit"; }
          setStatus("error", "Network error during submit.");
          setInsight("error", "Network error.");
        });
      return;
    }

    // Derive rejection_entries from the PLANNED slot state so the backend
    // always receives data that is consistent with the scanned assignments.
    // This prevents a stale-plan mismatch when the user edits qty after scanning.
    var planEntries = {};
    state.rejectSlots.forEach(function (slot) {
      var rid = slot.reason_id;
      if (!planEntries[rid]) {
        planEntries[rid] = { reason_id: rid, reason_text: slot.reason_text || "", qty: 0 };
      }
      planEntries[rid].qty += slot.qty;
    });
    var entries = Object.keys(planEntries).map(function (k) { return planEntries[k]; });
    if (!entries.length) { setStatus("error", "Enter at least one rejection qty."); setInsight("error", "No rejection qty."); return; }
    if (!rejectStepDone()) { setStatus("error", "Please scan all reject trays."); setInsight("error", "Reject scans incomplete."); return; }
    if (!acceptStepDone()) { setStatus("error", "Please scan all accept trays."); setInsight("error", "Accept scans incomplete."); return; }

    var payload = {
      lot_id: state.lotId,
      rejection_entries: entries,
      reject_assignments: state.rejectSlots.map(function (slot, i) {
        return { tray_id: state.rejectScans[i].tray_id, reason_id: slot.reason_id };
      }),
      delink_tray_ids: state.delinkScans.map(function (d) { return d.tray_id; }),
      accept_assignments: state.acceptSlots.map(function (_, i) {
        return { tray_id: state.acceptScans[i].tray_id };
      }),
      remarks: ($("isrm-remarks") || {}).value || "",
    };

    state.isSubmitting = true;
    var btn = $("isrm-submit-btn");
    btn.disabled = true; btn.textContent = "Submitting\u2026";
    setStatus("info", "Submitting\u2026");
    setInsight("busy", "Submitting\u2026");
    // ── Bug3: mark S circle as scanning-WIP (half-green) ──────────────────
    if (typeof window.isMarkSCircleWip === "function") {
      window.isMarkSCircleWip(state.lotId);
    }
    fetch("/inputscreening/partial_submit_v2/", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": getCsrf() },
      body: JSON.stringify(payload),
    })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, data: j }; }); })
      .then(function (resp) {
        state.isSubmitting = false;
        btn.textContent = "Submit";
        if (!resp.ok || !resp.data.success) {
          setStatus("error", (resp.data && resp.data.error) || "Submission failed.");
          setInsight("error", "Submit failed.");
          updateSubmitState();
          return;
        }
        clearDraft();
        setStatus("success", "Submitted successfully.");
        setInsight("success", "Submitted.");
        if (typeof Swal !== "undefined") {
          Swal.fire({
            icon: "success",
            title: "Partial Reject Submitted",
            text: "Reject: " + resp.data.total_reject_qty + " · Accept: " + resp.data.total_accept_qty,
            timer: 2200,
            showConfirmButton: false,
          }).then(function () { closeModal(); location.reload(); });
        } else {
          setTimeout(function () { closeModal(); location.reload(); }, 800);
        }
      })
      .catch(function () {
        state.isSubmitting = false;
        btn.textContent = "Submit";
        setStatus("error", "Network error during submit.");
        setInsight("error", "Network error.");
        updateSubmitState();
      });
  }

  // ── Wire-up ────────────────────────────────────────────────
  document.addEventListener("DOMContentLoaded", function () {
    document.addEventListener("click", function (e) {
      var btn = e.target.closest(".btn-reject-is");
      if (!btn) return;
      e.preventDefault();
      var lotId = btn.getAttribute("data-stock-lot-id");
      var batchId = btn.getAttribute("data-batch-id");
      if (!lotId) return;
      openModal(lotId, batchId);
    });

    var closeBtn = $("isrm-close-btn");
    if (closeBtn) closeBtn.addEventListener("click", closeModal);
    var cancelBtn = $("isrm-cancel-btn");
    if (cancelBtn) cancelBtn.addEventListener("click", closeModal);
    var submitBtn = $("isrm-submit-btn");
    if (submitBtn) submitBtn.addEventListener("click", submit);
    var clearBtn = $("isrm-clear-btn");
    if (clearBtn) clearBtn.addEventListener("click", clearAllInputs);
    var draftBtn = $("isrm-draft-btn");
    if (draftBtn) draftBtn.addEventListener("click", saveDraft);

    // ── Lot Rejection toggle ─────────────────────────────────────────
    // When checked: switch the modal to "full lot reject" mode, focus the
    // remarks box and let the operator submit immediately. The submit()
    // function detects state.fullLotReject and routes to /full_reject/.
    var lotRejToggle = $("isrm-lot-reject-toggle");
    if (lotRejToggle) {
      lotRejToggle.addEventListener("change", function () {
        state.fullLotReject = !!this.checked;
        var body = document.querySelector("#isRejectModal .isrm-body");
        var submitBtnEl = $("isrm-submit-btn");
        var rmEl = $("isrm-remarks");
        if (this.checked) {
          if (body) body.classList.add("isrm-full-reject-mode");
          if (submitBtnEl) {
            submitBtnEl.disabled = false;
            submitBtnEl.textContent = "Submit Lot Rejection";
          }
          setInsight(
            "warning",
            "Lot Rejection mode — enter remarks and click Submit."
          );
          setStatus(
            "warning",
            "Lot Rejection: the entire lot will be rejected. Remarks are required."
          );
          if (rmEl) {
            rmEl.focus();
            try { rmEl.scrollIntoView({ behavior: "smooth", block: "center" }); } catch (_) {}
          }
        } else {
          if (body) body.classList.remove("isrm-full-reject-mode");
          if (submitBtnEl) submitBtnEl.textContent = "Submit";
          setInsight("info", "Lot Rejection mode disabled.");
          setStatus("info", "Resume scanning to submit a partial reject.");
          updateSubmitState();
        }
      });
    }

    // NOTE: Intentionally removed backdrop click-to-close to prevent
    // accidental dismissal while scanning (Err1 fix).
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") {
        var m = $("isRejectModal");
        if (m && m.classList.contains("open")) closeModal();
      }
    });
  });

  window.__isrm = state;
})();

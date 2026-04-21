// ====================================================================
//  IS REJECT MODAL — Backend-driven (Brass QC parity, IS-scoped)
//  Wires up the "Reject" button on IS_PickTable to a server-side
//  allocator. The frontend never computes tray IDs or quantities;
//  it only renders what /inputscreening/reject_allocate/ returns.
// ====================================================================
(function () {
  'use strict';

  function getCookie(name) {
    var v = '; ' + document.cookie;
    var parts = v.split('; ' + name + '=');
    if (parts.length === 2) return parts.pop().split(';').shift();
    return '';
  }

  function escHtml(s) {
    var d = document.createElement('div');
    d.textContent = (s == null ? '' : String(s));
    return d.innerHTML;
  }

  // Convert tray type code to full name (J* -> Jumbo, N* -> Normal)
  function getTrayFullName(trayTypeCode) {
    if (!trayTypeCode) return trayTypeCode;
    var code = String(trayTypeCode).toUpperCase().trim();
    if (code.charAt(0) === 'J') return 'Jumbo';
    if (code.charAt(0) === 'N') return 'Normal';
    return trayTypeCode;
  }

  function ready(fn) {
    if (document.readyState !== 'loading') fn();
    else document.addEventListener('DOMContentLoaded', fn);
  }

  ready(function () {
    var modal = document.getElementById('trayScanModal');
    var body = document.getElementById('isRejectModalBody');
    if (!modal || !body) return;

    // ── DOM refs ──
    var elTrayType    = document.getElementById('isRejTrayType');
    var elCapacity    = document.getElementById('isRejTrayCapacity');
    var elTotalQty    = document.getElementById('isRejTotalQty');
    var elActiveCnt   = document.getElementById('isRejActiveTrayCount');
    var elTrayStrip   = document.getElementById('isRejActiveTraysStrip');
    var elTotalReject = document.getElementById('isRejTotalReject');
    var elBalance     = document.getElementById('isRejBalanceAccept');
    var elReasonsGrid = document.getElementById('isRejReasonsGrid');
    var elAllocSec    = document.getElementById('isRejAllocSection');
    var elAllocRej    = document.getElementById('isRejAllocRejList');
    var elAllocAcc    = document.getElementById('isRejAllocAccList');
    var elAllocRejQty = document.getElementById('isRejAllocRejQty');
    var elAllocAccQty = document.getElementById('isRejAllocAccQty');
    var elRemarks     = document.getElementById('isRejRemarks');
    var elRemarksSec  = document.getElementById('isRejRemarksSection');
    var elRemarksLbl  = document.getElementById('isRejRemarksLabel');
    var elFullLotCb   = document.getElementById('isRejFullLotCb');
    var elFullLotWrap = document.getElementById('isRejFullLotWrap');
    var elError       = document.getElementById('isRejError');
    var elCancelBtn   = document.getElementById('isRejCancelBtn');
    var elClearBtn    = document.getElementById('isRejClearBtn');
    var elSubmitBtn   = document.getElementById('isRejSubmitBtn');
    var elCloseBtn    = document.getElementById('closeTrayScanModal');
    var elHeaderQty   = document.getElementById('rejectionWindowLotQty');
    var elHeaderModel = modal.querySelector('.modal-model-no');

    // ── State ──
    var state = {
      lotId: null,
      totalQty: 0,
      capacity: 0,
      reasons: [],         // [{id, code, text}]
      allocTimer: null,
      lastAlloc: null,     // last successful allocation payload
      activeInput: null,   // last focused tray-scan input (chip-tap target)
      delinkCandidates: [],// cached delink candidates from last allocation
      activeTrays: [],     // immutable list of all active tray IDs of this lot (uppercase)
    };

    var REASONS_URL  = '/inputscreening/rejection_reasons/';
    var CONTEXT_URL  = '/inputscreening/reject_context/';
    var ALLOCATE_URL = '/inputscreening/reject_allocate/';
    var SUBMIT_URL   = '/inputscreening/reject_submit/';

    function showError(msg) {
      if (!elError) return;
      if (!msg) { elError.style.display = 'none'; elError.textContent = ''; return; }
      elError.textContent = msg;
      elError.style.display = 'block';
    }

    function closeModal() {
      modal.classList.remove('open');
      modal.style.display = 'none';
      state.lotId = null;
      state.lastAlloc = null;
      if (elFullLotCb) { elFullLotCb.checked = false; }
      if (elFullLotWrap) { elFullLotWrap.classList.remove('active'); }
      if (elRemarksSec) { elRemarksSec.classList.remove('required'); }
      if (elRemarksLbl) { elRemarksLbl.textContent = 'Remarks (optional)'; }
      if (typeof window.restoreRowPosition === 'function') window.restoreRowPosition();
    }

    function clearAllInputs() {
      // Clear all reason quantity inputs
      var qtyInputs = document.querySelectorAll('.is-reject-qty-input');
      qtyInputs.forEach(function(input) {
        input.value = '0';
      });
      
      // Clear all tray ID inputs in the allocation rows
      var trayIdInputs = document.querySelectorAll('.is-alloc-tray-scan-input');
      trayIdInputs.forEach(function(input) {
        input.value = '';
      });
      
      // Clear remarks
      if (elRemarks) { elRemarks.value = ''; }
      
      // Trigger allocation recalculation
      onQtyChange();
      
      console.log('[IS-Reject] All inputs cleared');
    }

    function openModal() {
      modal.classList.add('open');
      modal.style.display = 'flex';
    }

    if (elCancelBtn) elCancelBtn.addEventListener('click', closeModal);
    if (elCloseBtn) elCloseBtn.addEventListener('click', closeModal);
    if (elClearBtn) elClearBtn.addEventListener('click', clearAllInputs);

    // ── Lot Rejection checkbox: mandatory remark + autofocus ──
    if (elFullLotCb) {
      elFullLotCb.addEventListener('change', function () {
        applyFullLotState();
      });
    }

    function applyFullLotState() {
      var on = !!(elFullLotCb && elFullLotCb.checked);
      if (elFullLotWrap) elFullLotWrap.classList.toggle('active', on);
      if (elRemarksSec) elRemarksSec.classList.toggle('required', on);
      if (elRemarksLbl) elRemarksLbl.textContent = on ? 'Remarks (mandatory for Lot Rejection)' : 'Remarks (optional)';
      if (on) {
        // Auto-fill all reason inputs to zero except clear and prefill total qty in first input? Keep user control:
        // Just enable submit only when remark filled.
        if (elRemarks) {
          elRemarks.focus();
          elRemarks.classList.add('focus-pulse');
          setTimeout(function () { elRemarks.classList.remove('focus-pulse'); }, 400);
        }
      }
      revalidateSubmit();
    }

    if (elRemarks) {
      elRemarks.addEventListener('input', revalidateSubmit);
    }

    function revalidateSubmit() {
      if (!elSubmitBtn) return;
      var fullLot = !!(elFullLotCb && elFullLotCb.checked);
      var hasRemark = elRemarks && elRemarks.value.trim().length > 0;
      var totalRej = parseInt(elTotalReject.textContent || '0', 10) || 0;
      if (fullLot) {
        // Full lot rejection — submit allowed only with remark.
        elSubmitBtn.disabled = !hasRemark;
      } else if (totalRej > 0 && state.lastAlloc) {
        // Partial rejection — every rendered scan input must be a
        // verified valid tray ID before the operator can submit.
        elSubmitBtn.disabled = !allRowsValid();
      } else {
        elSubmitBtn.disabled = true;
      }
    }

    // ── Open modal: intercept the existing Reject button click ──
    document.addEventListener('click', function (e) {
      var btn = e.target.closest('.tray-scan-btn');
      if (!btn) return;
      // Skip the read-only "View" link (DayPlanning-view) and the Set Top Tray
      // button — we only handle real Reject buttons.
      if (btn.classList.contains('tray-scan-btn-DayPlanning-view') ||
          btn.classList.contains('tray-scan-btn-Jig')) return;
      if (btn.disabled || btn.getAttribute('disabled') !== null) return;

      // Only intercept the rejection variant (text contains "Reject" or
      // "Set Top Tray"). Set Top Tray uses the same class but is a different
      // workflow — defer to the existing handler in that case.
      var label = (btn.textContent || '').trim().toLowerCase();
      if (label.indexOf('reject') === -1) return;

      e.preventDefault();
      e.stopPropagation();

      var lotId   = btn.getAttribute('data-stock-lot-id');
      var batchId = btn.getAttribute('data-batch-id');
      if (!lotId) { console.warn('[IS-Reject] missing lot id'); return; }

      openRejectFlow(lotId, batchId, btn);
    }, true); // capture phase to beat any conflicting handler

    function openRejectFlow(lotId, batchId, btn) {
      state.lotId = lotId;
      showError('');
      elRemarks.value = '';
      elTotalReject.textContent = '0';
      elBalance.textContent = '0';
      elAllocSec.style.display = 'none';
      elSubmitBtn.disabled = true;
      elReasonsGrid.innerHTML = '<div class="is-reject-loading">Loading rejection reasons…</div>';

      // Pull row context for header preview (instant) before backend reply.
      var row = btn.closest('tr');
      if (row) {
        var rowQty = row.querySelector('.lot-qty');
        if (rowQty && elHeaderQty) elHeaderQty.textContent = rowQty.textContent.trim();
      }

      openModal();

      Promise.all([
        fetch(REASONS_URL, { credentials: 'same-origin' }).then(function (r) { return r.json(); }),
        fetch(CONTEXT_URL + '?lot_id=' + encodeURIComponent(lotId), { credentials: 'same-origin' })
          .then(function (r) { return r.json(); }),
      ]).then(function (results) {
        var reasonsRes = results[0] || {};
        var ctxRes = results[1] || {};

        if (!reasonsRes.success) throw new Error(reasonsRes.error || 'Failed to load reasons');
        if (!ctxRes.success) throw new Error(ctxRes.error || 'Failed to load lot context');

        state.reasons = reasonsRes.reasons || [];
        state.totalQty = ctxRes.total_qty || 0;
        state.capacity = ctxRes.tray_capacity || 0;

        elTrayType.textContent = getTrayFullName(ctxRes.tray_type) || '—';
        elCapacity.textContent = ctxRes.tray_capacity || '—';
        elTotalQty.textContent = ctxRes.total_qty || '—';
        if (elHeaderQty) elHeaderQty.textContent = ctxRes.total_qty || 0;
        if (elHeaderModel && ctxRes.model_no) elHeaderModel.textContent = ctxRes.model_no;

        renderReasons();
        // Fetch initial allocation structure (with reject_qty=0) on modal
        // open so operator sees what to expect before entering quantities.
        // This also populates active tray strip immediately.
        fetchAllocation(0);
      }).catch(function (err) {
        console.error('[IS-Reject] init error', err);
        elReasonsGrid.innerHTML =
          '<div class="is-reject-loading" style="color:#c62828;">Failed to load rejection data.</div>';
        showError(err.message || 'Failed to load rejection data');
      });
    }

    // ── Render the two-column reason list with live qty inputs ──
    function renderReasons() {
      if (!state.reasons.length) {
        elReasonsGrid.innerHTML =
          '<div class="is-reject-loading">No rejection reasons configured.</div>';
        return;
      }
      var html = '';
      state.reasons.forEach(function (r, i) {
        html +=
          '<div class="is-reject-reason-row">' +
            '<span class="seq">' + escHtml(r.rejection_reason_id || ('R' + (i + 1))) + '</span>' +
            '<span class="reason-text">' + escHtml(r.rejection_reason) + '</span>' +
            '<input type="number" min="0" max="' + state.totalQty + '" value="0" ' +
              'class="is-reject-qty-input" data-reason-id="' + r.id + '" inputmode="numeric" />' +
          '</div>';
      });
      elReasonsGrid.innerHTML = html;

      var inputs = elReasonsGrid.querySelectorAll('.is-reject-qty-input');
      inputs.forEach(function (inp) {
        inp.addEventListener('input', onQtyChange);
      });
    }

    // ── Compute totals locally (instant), debounce backend allocation ──
    function onQtyChange() {
      var total = 0;
      elReasonsGrid.querySelectorAll('.is-reject-qty-input').forEach(function (inp) {
        var v = parseInt(inp.value || '0', 10);
        if (isNaN(v) || v < 0) v = 0;
        if (v > state.totalQty) {
          v = state.totalQty;
          inp.value = v;
        }
        total += v;
        inp.classList.toggle('has-value', v > 0);
      });

      if (total > state.totalQty) {
        showError('Total reject qty (' + total + ') exceeds lot qty (' + state.totalQty + ')');
        elSubmitBtn.disabled = true;
        elTotalReject.textContent = total;
        elBalance.textContent = 0;
        elAllocSec.style.display = 'none';
        return;
      }
      showError('');
      elTotalReject.textContent = total;
      elBalance.textContent = Math.max(state.totalQty - total, 0);

      if (total <= 0) {
        elAllocSec.style.display = 'none';
        elSubmitBtn.disabled = true;
        state.lastAlloc = null;
        return;
      }
      // Debounce: wait 250 ms after the last keystroke.
      if (state.allocTimer) clearTimeout(state.allocTimer);
      state.allocTimer = setTimeout(function () { fetchAllocation(total); }, 250);
    }

    function fetchAllocation(rejectQty) {
      // Send per-reason map so backend can split trays by reason
      // (one tray = one reason, strictly enforced server-side).
      var reasons = collectReasonsArray();
      fetch(ALLOCATE_URL, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCookie('csrftoken'),
        },
        body: JSON.stringify({
          lot_id: state.lotId,
          reject_qty: rejectQty,
          reasons: reasons,
        }),
      }).then(function (r) { return r.json(); }).then(function (resp) {
        if (!resp.success) {
          showError(resp.error || 'Allocation failed');
          elAllocSec.style.display = 'none';
          elSubmitBtn.disabled = true;
          return;
        }
        state.lastAlloc = resp;
        renderAllocation(resp);
        elAllocSec.style.display = '';
        revalidateSubmit();
      }).catch(function (err) {
        console.error('[IS-Reject] allocate error', err);
        showError('Network error while allocating trays');
        elSubmitBtn.disabled = true;
      });
    }

    // Collect [{reason_id, qty}] from the live inputs.
    function collectReasonsArray() {
      var out = [];
      elReasonsGrid.querySelectorAll('.is-reject-qty-input').forEach(function (inp) {
        var qty = parseInt(inp.value || '0', 10);
        if (qty > 0) {
          out.push({
            reason_id: parseInt(inp.getAttribute('data-reason-id'), 10),
            qty: qty,
          });
        }
      });
      return out;
    }

    function renderAllocation(resp) {
      elAllocRejQty.textContent = resp.reject_qty;
      elAllocAccQty.textContent = resp.accept_qty;
      elAllocRej.innerHTML = renderSlotList(resp.reject_slots, 'reject');
      elAllocAcc.innerHTML = renderSlotList(resp.accept_slots, 'accept');
      // Cache delink candidates to render conditionally after reject scans.
      state.delinkCandidates = resp.delink_candidates || [];
      // Cache ALL active trays of the lot — operator may delink ANY of them.
      state.activeTrays = (resp.active_trays || []).map(function (t) {
        return String(t.tray_id || '').trim().toUpperCase();
      }).filter(Boolean);
      // Refresh active tray chips with the latest server view.
      renderActiveTrayStrip(resp.active_trays || []);
      // Reuse availability summary (Reusable / New / Delink) chip strip.
      renderReuseSummary(resp.reuse_summary || null);
      // Render delink section (will stay hidden until reject scans complete).
      renderDelinkSection(state.delinkCandidates);
      // Apply factory workflow gates: reject -> delink -> accept.
      applyStageGates();
      // Defensive: drop any obsolete workflow-steps banner that earlier
      // builds may have injected. We never render it again.
      var stale = document.getElementById('isRejWorkflowSteps');
      if (stale && stale.parentNode) stale.parentNode.removeChild(stale);
    }

    // ── Reuse summary banner: Reusable / New required / Delink available ──
    function renderReuseSummary(summary) {
      var host = document.getElementById('isRejReuseSummary');
      if (!summary) {
        if (host) host.innerHTML = '';
        return;
      }
      if (!host) {
        host = document.createElement('div');
        host.id = 'isRejReuseSummary';
        host.className = 'is-reject-reuse-summary';
        host.style.cssText =
          'display:flex; gap:8px; flex-wrap:wrap; margin:6px 0 10px;' +
          'font-size:11px; font-weight:700; letter-spacing:.3px;';
        if (elAllocSec && elAllocSec.parentNode) {
          elAllocSec.parentNode.insertBefore(host, elAllocSec);
        }
      }
      function chip(label, value, bg, fg, border) {
        return (
          '<span style="background:' + bg + '; color:' + fg + ';' +
          ' border:1px solid ' + border + '; padding:4px 10px; border-radius:14px;">' +
          escHtml(label) + ' : <strong>' + (value | 0) + '</strong></span>'
        );
      }
      host.innerHTML =
        chip('Reusable Existing Trays', summary.reusable_existing,
             '#fff3e0', '#e65100', '#ffcc80') +
        chip('New Trays Required', summary.new_required,
             '#e3f2fd', '#1565c0', '#90caf9') +
        chip('Delink Trays Available', summary.delink_available,
             '#f3e5f5', '#6a1b9a', '#ce93d8');
    }

    function fetchActiveTrayStrip() {
      // Use ALLOCATE with reject_qty=0 to receive the canonical active_trays
      // list from the backend without duplicating logic.
      if (!state.lotId) return;
      fetch(ALLOCATE_URL, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCookie('csrftoken'),
        },
        body: JSON.stringify({ lot_id: state.lotId, reject_qty: 0 }),
      }).then(function (r) { return r.json(); }).then(function (resp) {
        if (resp && resp.success) {
          state.activeTrays = (resp.active_trays || []).map(function (t) {
            return String(t.tray_id || '').trim().toUpperCase();
          }).filter(Boolean);
          renderActiveTrayStrip(resp.active_trays || []);
        }
      }).catch(function () { /* non-blocking */ });
    }

    function renderActiveTrayStrip(trays) {
      if (!elTrayStrip || !elActiveCnt) return;
      elActiveCnt.textContent = trays.length || 0;
      if (!trays.length) {
        elTrayStrip.style.display = 'none';
        elTrayStrip.innerHTML = '';
        return;
      }
      // ✅ FIX: TOP badge is rendered ONLY ONCE on the actual physical top tray
      // (backend marks ``is_top`` exactly once). Check for duplicate TOP to prevent UI bug.
      var foundTop = false;
      elTrayStrip.innerHTML = trays.map(function (t) {
        var showTop = t.is_top && !foundTop;
        if (showTop) foundTop = true;
        var topCls = showTop ? ' top' : '';
        return (
          '<span class="is-reject-tray-chip' + topCls + '"' +
            ' data-tray-id="' + escHtml(t.tray_id) + '"' +
            ' role="button" tabindex="0"' +
            ' title="Tap to fill the active scan box"' +
            ' style="cursor:pointer;">' +
            escHtml(t.tray_id) +
            (showTop ? ' <span class="badge top" style="background:#ffe0b2;color:#bf360c;font-size:10px;padding:1px 6px;border-radius:8px;margin-left:4px;">TOP</span>' : '') +
            '<span class="qty">' + (t.qty || 0) + '</span>' +
          '</span>'
        );
      }).join('');
      elTrayStrip.style.display = 'flex';
    }

    // ── Tap-to-fill: clicking any active-tray chip pushes its tray_id
    //    into whichever scan input was last focused (or the first empty
    //    reject input as a sensible fallback). ──
    if (elTrayStrip) {
      elTrayStrip.addEventListener('click', function (e) {
        var chip = e.target.closest('.is-reject-tray-chip');
        if (!chip) return;
        var trayId = chip.getAttribute('data-tray-id') || '';
        if (!trayId) return;
        fillScanInput(trayId);
      });
    }

    function fillScanInput(trayId) {
      var target = state.activeInput;
      if (!target || !document.body.contains(target)) {
        // Fallback: first empty reject scan input.
        target = elAllocRej && elAllocRej.querySelector('.is-reject-tray-scan-input:placeholder-shown')
              || elAllocRej && elAllocRej.querySelector('.is-reject-tray-scan-input');
      }
      if (!target) return;
      target.value = trayId;
      target.dispatchEvent(new Event('input', { bubbles: true }));
      target.focus();
      revalidateSubmit();
    }

    function renderSlotList(slots, side) {
      if (!slots || !slots.length) {
        return '<div class="is-reject-alloc-empty">No trays needed</div>';
      }
      var sideKey = side || 'reject';
      return slots.map(function (s, i) {
        // TOP badge — accept side only and only on the physical top row.
        // Reject side never shows TOP (factory rule: TOP belongs to accept).
        var topBadge = (sideKey === 'accept' && s.is_top)
          ? '<span class="badge top">TOP</span>' : '';
        var reasonBadge = s.reason_code
          ? '<span class="badge" style="background:#ffebee;color:#c62828;border:1px solid #ef9a9a;">'
              + escHtml(s.reason_code) + '</span>'
          : '';
        // ⚠️ NO auto-populated tray_id. Operator must scan/tap.
        // Source badge (Reused/New) is shown initially but replaced with
        // 'Scanned' status once operator enters a tray_id (see onTrayInput).
        var srcClass = (s.source || '').toLowerCase() === 'reused' ? 'reused' : 'new';
        // Tray IDs follow the XX-A##### convention (8 chars). Cap input
        // length defensively so accidental over-typing cannot smuggle in
        // garbage. Real scanners always emit the full ID at once.
        var maxChars = 12;
        var dataAttrs =
          ' data-side="' + sideKey + '"' +
          ' data-slot-index="' + i + '"' +
          ' data-expected-qty="' + (s.qty || 0) + '"' +
          ' data-is-top="' + (s.is_top ? '1' : '0') + '"' +
          ' data-source="' + escHtml(s.source || 'New') + '"' +
          (s.reason_id ? ' data-reason-id="' + s.reason_id + '"' : '') +
          (s.candidate_tray_id ? ' data-candidate="' + escHtml(s.candidate_tray_id) + '"' : '');
        // Accept inputs start disabled — operator must finish reject scans first.
        var isAccept = sideKey === 'accept';
        var initDisabled = isAccept ? ' disabled' : '';
        var initPlaceholder = isAccept ? 'Complete reject trays first' : 'Scan tray';
        var initBg = isAccept ? '#f5f5f5' : '#fff';
        return (
          '<div class="is-reject-alloc-row" ' + dataAttrs + '>' +
            '<span class="sno" style="min-width:26px; max-width:26px;">' + (i + 1) + '</span>' +
            '<span class="tray-id" style="display:flex; flex-direction:column; gap:4px; flex:1; min-width:140px;">' +
              '<div style="display:flex; align-items:center; gap:4px;">' +
                '<input type="text" class="is-reject-tray-scan-input"' + initDisabled +
                  ' placeholder="' + initPlaceholder + '" autocomplete="off" spellcheck="false"' +
                  ' maxlength="' + maxChars + '"' +
                  ' style="flex:1; padding:4px 6px; border:1px solid #b2dfdb; border-radius:4px;' +
                  ' font-family:monospace; font-size:11px; background:' + initBg + '; text-transform:uppercase; min-width:90px;" />' +
                '<button class="is-reject-clear-btn" title="Clear tray" ' +
                  'style="background:#ffebee; color:#c62828; border:1px solid #ef9a9a; ' +
                  'border-radius:4px; width:20px; height:20px; cursor:pointer; font-size:12px; ' +
                  'display:flex; align-items:center; justify-content:center; padding:0; flex-shrink:0;">✕</button>' +
                topBadge + ' ' + reasonBadge +
                '<span class="is-reject-scan-status" style="font-size:10px; font-weight:700; min-width:50px; max-width:70px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;"></span>' +
              '</div>' +
              '<div class="is-reject-suggestion" style="display:none; margin-left:4px;"></div>' +
            '</span>' +
            '<span class="qty" style="min-width:32px; max-width:40px; text-align:right;">' + s.qty + '</span>' +
            '<span class="badge ' + srcClass + ' is-reject-source-badge" data-source="' + escHtml(s.source || 'New') + '" style="min-width:50px; max-width:65px; font-size:10px; padding:2px 6px;">' + escHtml(s.source || 'New') + '</span>' +
          '</div>'
        );
      }).join('');
    }

    // ── Scan validation ────────────────────────────────────────────
    // Backend-driven validation querying the actual TrayId / IPTrayId
    // tables so the operator sees database-accurate availability status.
    var VALIDATE_TRAY_URL = '/inputscreening/validate_reject_tray/';
    var validationCache = {}; // {tray_id: {valid, error, timestamp}}
    var CACHE_TTL = 5000; // 5 sec — fresh enough for scanner bursts

    function getAllScanInputs() {
      return Array.prototype.slice.call(
        modal.querySelectorAll('.is-reject-tray-scan-input')
      );
    }

    function getRejectInputs() {
      return elAllocRej
        ? Array.prototype.slice.call(elAllocRej.querySelectorAll('.is-reject-tray-scan-input'))
        : [];
    }

    function getAcceptInputs() {
      return elAllocAcc
        ? Array.prototype.slice.call(elAllocAcc.querySelectorAll('.is-reject-tray-scan-input'))
        : [];
    }

    function isInputValid(inp) {
      var raw = (inp.value || '').trim();
      if (!raw) return false;
      var row = inp.closest('.is-reject-alloc-row');
      if (!row) return false;
      var trayStatus = row.getAttribute('data-tray-status') || '';
      return trayStatus === 'reused' || trayStatus === 'new';
    }

    function allRejectInputsValid() {
      var inputs = getRejectInputs();
      if (!inputs.length) return false;
      for (var i = 0; i < inputs.length; i++) {
        if (!isInputValid(inputs[i])) return false;
      }
      return true;
    }

    // Stage gates: REJECT first → DELINK (if any) → ACCEPT TOP → rest of ACCEPT.
    // Accept TOP unlocks only after every reject input is Valid ✅.
    // Remaining accept rows unlock + auto-fill only after TOP is Valid ✅.
    function applyStageGates() {
      var rejectDone = allRejectInputsValid();
      var acceptInputs = getAcceptInputs();

      // Find TOP accept input (the row with data-is-top="1").
      var topAcceptInp = null;
      acceptInputs.forEach(function (inp) {
        var row = inp.closest('.is-reject-alloc-row');
        if (row && row.getAttribute('data-is-top') === '1' && !topAcceptInp) {
          topAcceptInp = inp;
        }
      });
      // Fallback: first accept input is TOP if backend didn't mark one.
      if (!topAcceptInp && acceptInputs.length) topAcceptInp = acceptInputs[0];

      var topValid = topAcceptInp ? isInputValid(topAcceptInp) : false;

      acceptInputs.forEach(function (inp) {
        var isTop = (inp === topAcceptInp);
        var shouldEnable;
        var placeholder;
        if (!rejectDone) {
          shouldEnable = false;
          placeholder = 'Complete reject trays first';
        } else if (isTop) {
          shouldEnable = true;
          placeholder = 'Scan TOP accept tray';
        } else {
          shouldEnable = topValid;
          placeholder = topValid ? 'Scan tray' : 'Scan TOP accept tray first';
        }
        if (shouldEnable) {
          if (inp.disabled) {
            inp.disabled = false;
            inp.placeholder = placeholder;
            inp.style.background = '#fff';
          } else if (inp.placeholder !== placeholder) {
            inp.placeholder = placeholder;
          }
        } else {
          if (!(inp.value || '').trim()) {
            inp.disabled = true;
            inp.placeholder = placeholder;
            inp.style.background = '#f5f5f5';
          }
        }
      });

      // Auto-fill remaining accept rows once TOP is valid (one-time per
      // TOP unlock; only fills empty rows so manual scans win).
      if (rejectDone && topValid) {
        autoFillRemainingAccept(topAcceptInp);
      }

      // Toggle delink section visibility (after reject done) and rebuild
      // its eligible pool so any tray actually scanned in reject/accept is
      // excluded — a tray cannot be both used and delinked (CASE 4).
      refreshDelinkExclusions();
      var delinkContainer = document.getElementById('isRejDelinkSection');
      var hasDelinkSlots = (state.delinkCandidates || []).length > 0;
      if (delinkContainer) {
        if (rejectDone && hasDelinkSlots) {
          delinkContainer.style.display = '';
        } else {
          delinkContainer.style.display = 'none';
        }
      }
    }

    // Recompute delink eligible pool by removing any tray IDs that the
    // operator has scanned into reject/accept rows. Updates chip strip
    // and the Reuse Summary's ``Delink Trays Available`` chip in place.
    //
    // ✅ Reuse-budget rule (factory truth):
    //   Backend's ``newly_emptied`` candidates represent the SAME reuse
    //   opportunity already counted in ``reusable_existing``. Every time
    //   the operator scans a REUSED tray for a reject slot, one of those
    //   opportunities is consumed — so the "newly_emptied" delink pool
    //   must shrink by the same amount.
    //   ``existing`` candidates (already DB-flagged delink_tray=True) are
    //   independent and never consumed by reject scans.
    function refreshDelinkExclusions() {
      // Operator-driven delink: pool = ALL active trays of the lot.
      // We no longer suggest tray IDs, so the chip strip is intentionally
      // left empty. Slot count is still controlled by backend
      // (state.delinkCandidates.length).
      state.delinkEligible = (state.activeTrays || []).slice();
      var chipsHost = document.getElementById('isRejDelinkChips');
      if (chipsHost) chipsHost.innerHTML = '';
      // Keep the Reuse Summary chip in sync with the backend value
      // (delink_available is computed server-side from delink_candidates).
      var summaryHost = document.getElementById('isRejReuseSummary');
      if (summaryHost && state.lastAlloc && state.lastAlloc.reuse_summary) {
        var s = state.lastAlloc.reuse_summary;
        var chips = summaryHost.querySelectorAll('span > strong');
        if (chips && chips.length >= 3) {
          chips[2].textContent = (s.delink_available | 0);
        }
      }
    }

    // Populate remaining accept inputs from the LEFTOVER active trays
    // (anything not already scanned in reject / accept-TOP / delink).
    // Backend-supplied ``data-candidate`` is preferred only when that
    // candidate is still leftover; otherwise we pick the next unused
    // tray from the lot's active-tray list. Skips the TOP row and any
    // row the operator already touched.
    function autoFillRemainingAccept(topInp) {
      var acceptInputs = getAcceptInputs();

      // Build the "used" set: every tray ID currently sitting in any
      // reject input, accept input, or delink input.
      var used = {};
      getAllScanInputs().forEach(function (inp) {
        var v = (inp.value || '').trim().toUpperCase();
        if (v) used[v] = 1;
      });
      document.querySelectorAll('.is-reject-delink-scan-input').forEach(function (inp) {
        var v = (inp.value || '').trim().toUpperCase();
        if (v) used[v] = 1;
      });

      // Leftover queue from this lot's active trays, in backend order.
      var leftover = (state.activeTrays || []).filter(function (t) {
        return !used[t];
      });

      acceptInputs.forEach(function (inp) {
        if (inp === topInp) return;
        if ((inp.value || '').trim()) return;     // operator-typed wins
        if (inp.disabled) return;
        var row = inp.closest('.is-reject-alloc-row');
        if (!row) return;
        // Skip rows that are blocked because their tray was delinked.
        if (row.getAttribute('data-blocked-by-delink') === '1') return;

        // Prefer the row's backend candidate if it is still leftover.
        var pick = '';
        var cand = (row.getAttribute('data-candidate') || '').toUpperCase();
        if (cand && !used[cand]) {
          pick = cand;
          var idx = leftover.indexOf(cand);
          if (idx >= 0) leftover.splice(idx, 1);
        } else if (leftover.length) {
          pick = leftover.shift();
        }
        if (!pick) return;

        used[pick] = 1;
        inp.value = pick;
        // Trigger validation → paints status + revalidates submit.
        inp.dispatchEvent(new Event('input', { bubbles: true }));
      });
    }

    function validateTrayInputBackend(inputEl, callback) {
      var row = inputEl.closest('.is-reject-alloc-row');
      if (!row) return callback({ state: 'empty' });
      var raw = (inputEl.value || '').trim().toUpperCase();
      if (!raw) return callback({ state: 'empty' });

      // ✅ FIX: Pool-based validation (not position-based)
      // ANY eligible tray can be used in ANY slot — no strict candidate matching.
      // Backend validates: (1) format, (2) availability, (3) lot ownership.
      // Frontend ensures: (1) no duplicates within modal, (2) all slots filled.
      
      // Check for duplicates within modal FIRST (before backend call)
      var allInputs = getAllScanInputs();
      var seenTrays = [];
      for (var i = 0; i < allInputs.length; i++) {
        var inp = allInputs[i];
        if (inp === inputEl) continue; // skip self
        var otherTray = (inp.value || '').trim().toUpperCase();
        if (otherTray && otherTray === raw) {
          return callback({ 
            state: 'invalid', 
            reason: 'Duplicate: already used in this modal',
            suggestions: []
          });
        }
      }

      // Check cache first
      var now = Date.now();
      if (validationCache[raw] && (now - validationCache[raw].timestamp < CACHE_TTL)) {
        var cached = validationCache[raw];
        if (cached.valid) {
          return callback({ state: 'valid' });
        } else {
          return callback({ state: 'invalid', reason: cached.error || 'Invalid' });
        }
      }

      // Backend call (pool-based validation). Backend returns:
      //   { valid, tray_status: 'new'|'reused'|'invalid', reason }
      // No tray suggestions are ever surfaced (operator decides physically).
      fetch(VALIDATE_TRAY_URL + '?tray_id=' + encodeURIComponent(raw) + '&lot_id=' + encodeURIComponent(state.lotId), {
        credentials: 'same-origin',
      }).then(function (r) { return r.json(); }).then(function (resp) {
        var trayStatus = resp.tray_status || (resp.valid ? 'reused' : 'invalid');
        validationCache[raw] = {
          valid: !!resp.valid,
          tray_status: trayStatus,
          reason: resp.reason || resp.error || '',
          timestamp: Date.now(),
        };
        if (resp.valid) {
          // Enforce reuse limit dynamically against backend pool size.
          if (trayStatus === 'reused' && exceedsReuseLimit(inputEl, raw)) {
            callback({ state: 'invalid', tray_status: 'invalid',
              reason: 'Reuse limit exceeded for this lot' });
            return;
          }
          callback({ state: 'valid', tray_status: trayStatus });
        } else {
          callback({ state: 'invalid', tray_status: 'invalid',
            reason: resp.reason || resp.error || 'Not available' });
        }
      }).catch(function (err) {
        console.error('[IS-Reject] validate_tray error', err);
        callback({ state: 'invalid', tray_status: 'invalid', reason: 'Network error' });
      });
    }

    // Reuse limit: at most ``reuse_summary.reusable_existing`` reject inputs
    // may be marked as reused. If the operator scans more reused trays than
    // the backend pool allows, additional ones are flagged invalid.
    function exceedsReuseLimit(currentInput, currentRaw) {
      var alloc = state.lastAlloc;
      var limit = (alloc && alloc.reuse_summary && alloc.reuse_summary.reusable_existing) | 0;
      var rejectInputs = getRejectInputs();
      var reusedCount = 0;
      for (var i = 0; i < rejectInputs.length; i++) {
        var inp = rejectInputs[i];
        var v = (inp.value || '').trim().toUpperCase();
        if (!v) continue;
        if (inp === currentInput) {
          // The current scan would itself add 1 if accepted.
          continue;
        }
        var row = inp.closest('.is-reject-alloc-row');
        if (row && row.getAttribute('data-tray-status') === 'reused') {
          reusedCount++;
        }
      }
      // +1 for the candidate scan being validated now.
      return (reusedCount + 1) > limit;
    }

    function paintRowState(inputEl, result) {
      var row = inputEl.closest('.is-reject-alloc-row');
      if (!row) return;
      var status = row.querySelector('.is-reject-scan-status');
      var badge = row.querySelector('.is-reject-source-badge');
      var suggestionEl = row.querySelector('.is-reject-suggestion');

      // Always remove any leftover suggestion DOM (suggestions are no
      // longer rendered — operator decides tray physically).
      if (suggestionEl) {
        suggestionEl.style.display = 'none';
        suggestionEl.innerHTML = '';
      }

      if (result.state === 'valid') {
        var trayStatus = result.tray_status === 'new' ? 'new' : 'reused';
        inputEl.style.borderColor = '#43a047';
        inputEl.style.background = '#e8f5e9';
        if (status) {
          status.textContent = trayStatus === 'new' ? 'NEW TRAY' : 'REUSED TRAY';
          status.style.color = trayStatus === 'new' ? '#1565c0' : '#e65100';
          status.title = '';
        }
        // Refresh source badge label so it matches the live scan classification.
        if (badge) {
          badge.style.display = 'inline-block';
          badge.textContent = trayStatus === 'new' ? 'New' : 'Reused';
          badge.className = 'badge ' + (trayStatus === 'new' ? 'new' : 'reused')
            + ' is-reject-source-badge';
          badge.setAttribute('data-source', trayStatus === 'new' ? 'New' : 'Reused');
        }
        row.setAttribute('data-tray-status', trayStatus);
      } else if (result.state === 'invalid') {
        inputEl.style.borderColor = '#c62828';
        inputEl.style.background = '#ffebee';
        if (status) {
          status.textContent = 'INVALID TRAY';
          status.style.color = '#c62828';
          status.title = result.reason || '';
        }
        if (badge) badge.style.display = 'none';
        row.setAttribute('data-tray-status', 'invalid');
      } else { // empty / validating
        inputEl.style.borderColor = '#b2dfdb';
        inputEl.style.background = '#fff';
        if (status) { status.textContent = ''; status.title = ''; }
        if (badge) badge.style.display = 'inline-block';
        row.removeAttribute('data-tray-status');
      }
    }

    function focusNextEmptyInput(currentInput) {
      var all = getAllScanInputs();
      var idx = all.indexOf(currentInput);
      if (idx < 0) return;
      // Walk forward looking for an empty, enabled input.
      for (var step = 1; step < all.length; step++) {
        var nxt = all[idx + step];
        if (!nxt) break;
        if (nxt.disabled) continue;
        var raw = (nxt.value || '').trim();
        if (!raw) { nxt.focus(); return; }
      }
      // All downstream slots filled — check for delink section next.
      // ✅ FIX: Jump to delink section if it exists and has empty checkboxes
      var delinkSection = document.getElementById('isRejDelinkList');
      if (delinkSection) {
        var firstUnchecked = delinkSection.querySelector('input[type="checkbox"]:not(:checked)');
        if (firstUnchecked) {
          firstUnchecked.focus();
          return;
        }
      }
    }

    function allRowsValid() {
      var inputs = getAllScanInputs();
      if (!inputs.length) return false;
      for (var i = 0; i < inputs.length; i++) {
        if (!isInputValid(inputs[i])) return false;
      }
      return true;
    }

    // Delegated input handler — runs on every keystroke / scanner burst.
    var inputDebounceTimer = null;
    document.addEventListener('input', function (e) {
      if (!e.target.classList.contains('is-reject-tray-scan-input')) return;
      var inp = e.target;
      // Force uppercase so case-sensitive equality works for scanners
      // that emit lowercase (some Honeywell models do).
      var caretEnd = inp.selectionEnd;
      var upper = (inp.value || '').toUpperCase();
      if (upper !== inp.value) {
        inp.value = upper;
        try { inp.setSelectionRange(caretEnd, caretEnd); } catch (_) {}
      }
      // Show "validating…" briefly
      paintRowState(inp, { state: 'validating' });
      // Debounce backend call by 300ms so rapid typing doesn't spam
      if (inputDebounceTimer) clearTimeout(inputDebounceTimer);
      inputDebounceTimer = setTimeout(function () {
        validateTrayInputBackend(inp, function (result) {
          paintRowState(inp, result);
          applyStageGates();
          revalidateSubmit();
          // Auto-advance once a valid full-length scan has landed.
          if (result.state === 'valid') {
            // Defer a tick so the operator briefly sees the green state
            // before focus jumps; also lets scanner Enter terminator pass.
            setTimeout(function () { focusNextEmptyInput(inp); }, 60);
          }
        });
      }, 300);
    });
    document.addEventListener('focusin', function (e) {
      if (e.target && e.target.classList &&
          e.target.classList.contains('is-reject-tray-scan-input')) {
        state.activeInput = e.target;
      }
    });

    // ✅ FIX: Clear button handler (removes tray assignment and resets state)
    document.addEventListener('click', function (e) {
      if (!e.target.classList.contains('is-reject-clear-btn')) return;
      e.preventDefault();
      var btn = e.target;
      var row = btn.closest('.is-reject-alloc-row');
      if (!row) return;
      var inp = row.querySelector('.is-reject-tray-scan-input');
      if (!inp) return;
      
      // Clear input value and reset visual state
      inp.value = '';
      paintRowState(inp, { state: 'empty' });
      
      // Clear validation cache for this tray
      var wasValue = inp.value.trim().toUpperCase();
      if (wasValue && validationCache[wasValue]) {
        delete validationCache[wasValue];
      }
      
      // Revalidate submit button state
      revalidateSubmit();
      applyStageGates();
      
      // Focus the cleared input
      inp.focus();
    });

    // ✅ FIX: Suggestion button handler (auto-fills suggested tray)
    document.addEventListener('click', function (e) {
      if (!e.target.classList.contains('is-reject-suggestion-btn')) return;
      e.preventDefault();
      var btn = e.target;
      var suggestedTray = btn.getAttribute('data-tray-id');
      if (!suggestedTray) return;
      
      var row = btn.closest('.is-reject-alloc-row');
      if (!row) return;
      var inp = row.querySelector('.is-reject-tray-scan-input');
      if (!inp) return;
      
      // Fill the input with suggested tray
      inp.value = suggestedTray.toUpperCase();
      
      // Trigger validation
      inp.dispatchEvent(new Event('input', { bubbles: true }));
      inp.focus();
    });

    // ══════════════════════════════════════════════════════════════════
    // DELINK SECTION RENDERING
    // (always starts hidden; applyStageGates() reveals it after all
    //  reject tray inputs are valid)
    // ══════════════════════════════════════════════════════════════════
    function renderDelinkSection(candidates) {
      var container = document.getElementById('isRejDelinkSection');
      
      // Create container if doesn't exist
      if (!container) {
        container = document.createElement('div');
        container.id = 'isRejDelinkSection';
        container.className = 'is-reject-section';
        container.style.cssText = 'display:none;';
        
        // Insert after allocation section
        var allocSection = document.getElementById('isRejAllocSection');
        if (allocSection && allocSection.parentNode) {
          allocSection.parentNode.insertBefore(container, allocSection.nextSibling);
        }
      }
      
      if (!candidates || !candidates.length) {
        container.style.display = 'none';
        container.innerHTML = '';
        return;
      }

      // Render content but keep hidden — applyStageGates() will reveal
      // once all reject tray inputs are valid.
      container.style.display = 'none';
      // Pool of eligible delink trays = ALL active trays of this lot.
      // Operator chooses any of them; we never auto-suggest.
      state.delinkEligible = (state.activeTrays || []).slice();
      var slotCount = candidates.length;
      var chipsHtml = '';
      var slotsHtml = '';
      for (var i = 0; i < slotCount; i++) {
        slotsHtml +=
          '<div class="is-reject-delink-row" data-slot-index="' + i + '" ' +
            'style="display:flex; align-items:center; gap:6px;">' +
            '<span class="sno" style="min-width:26px; max-width:26px;">' + (i + 1) + '</span>' +
            '<input type="text" class="is-reject-delink-scan-input"' +
              ' placeholder="Scan / tap tray to delink" autocomplete="off"' +
              ' spellcheck="false" maxlength="12"' +
              ' style="flex:1; padding:4px 6px; border:1px solid #ce93d8;' +
              ' border-radius:4px; font-family:monospace; font-size:11px;' +
              ' background:#fff; text-transform:uppercase; min-width:120px;" />' +
            '<button class="is-reject-delink-clear-btn" title="Clear" ' +
              'style="background:#ffebee; color:#c62828; border:1px solid #ef9a9a;' +
              ' border-radius:4px; width:20px; height:20px; cursor:pointer;' +
              ' font-size:12px; display:flex; align-items:center;' +
              ' justify-content:center; padding:0; flex-shrink:0;">✕</button>' +
            '<span class="is-reject-delink-status" style="font-size:10px;' +
              ' font-weight:700; min-width:60px; white-space:nowrap;"></span>' +
          '</div>';
      }
      container.innerHTML =
        '<div class="is-reject-section-title">🗑️ Delink Trays (Optional)</div>' +
        '<div class="is-reject-delink-info" style="font-size:11px; color:#616161;' +
          ' margin-bottom:6px;">Scan or tap an eligible tray to remove it from the lot.</div>' +
        '<div id="isRejDelinkChips" style="display:flex; flex-wrap:wrap; gap:6px;' +
          ' margin-bottom:8px;">' + chipsHtml + '</div>' +
        '<div id="isRejDelinkList" class="is-reject-delink-list"' +
          ' style="display:flex; flex-direction:column; gap:6px;">' + slotsHtml + '</div>';
    }

    // Validate a delink scan against the eligible pool. Mirrors the
    // visual conventions of the reject input painter.
    function paintDelinkRow(inp, result) {
      var row = inp.closest('.is-reject-delink-row');
      if (!row) return;
      var status = row.querySelector('.is-reject-delink-status');
      if (result.state === 'valid') {
        inp.style.borderColor = '#43a047';
        inp.style.background = '#e8f5e9';
        if (status) {
          status.textContent = 'Valid ✅';
          status.style.color = '#2e7d32';
          status.title = '';
        }
      } else if (result.state === 'invalid') {
        inp.style.borderColor = '#c62828';
        inp.style.background = '#ffebee';
        if (status) {
          status.textContent = 'Invalid ❌';
          status.style.color = '#c62828';
          status.title = result.reason || '';
        }
      } else {
        inp.style.borderColor = '#ce93d8';
        inp.style.background = '#fff';
        if (status) { status.textContent = ''; status.title = ''; }
      }
    }

    function validateDelinkInput(inp) {
      var raw = (inp.value || '').trim().toUpperCase();
      if (!raw) {
        paintDelinkRow(inp, { state: 'empty' });
        syncBlockedByDelink();
        return;
      }
      // Eligibility = ANY active tray of this lot. Operator decides.
      var pool = state.activeTrays || [];
      if (pool.indexOf(raw) < 0) {
        paintDelinkRow(inp, { state: 'invalid', reason: 'Not a tray of this lot' });
        syncBlockedByDelink();
        return;
      }
      // Duplicate check within delink slots only (delink wins over accept).
      var others = document.querySelectorAll('.is-reject-delink-scan-input');
      for (var i = 0; i < others.length; i++) {
        var other = others[i];
        if (other === inp) continue;
        if ((other.value || '').trim().toUpperCase() === raw) {
          paintDelinkRow(inp, { state: 'invalid', reason: 'Already selected for delink' });
          syncBlockedByDelink();
          return;
        }
      }
      paintDelinkRow(inp, { state: 'valid' });
      syncBlockedByDelink();
    }

    // ── Delink wins: any alloc row whose scanned tray is now selected
    //    for delink gets greyed out, disabled and marked DELINKED.
    //    Clearing the delink selection restores the row's normal state.
    function getCurrentDelinkSet() {
      var set = {};
      document.querySelectorAll('.is-reject-delink-scan-input').forEach(function (inp) {
        var v = (inp.value || '').trim().toUpperCase();
        if (v) set[v] = 1;
      });
      return set;
    }

    function syncBlockedByDelink() {
      var delinked = getCurrentDelinkSet();
      var rows = modal.querySelectorAll('.is-reject-alloc-row');
      rows.forEach(function (row) {
        var inp = row.querySelector('.is-reject-tray-scan-input');
        if (!inp) return;
        var val = (inp.value || '').trim().toUpperCase();
        var status = row.querySelector('.is-reject-scan-status');
        var badge = row.querySelector('.is-reject-source-badge');
        var isBlocked = !!(val && delinked[val]);
        var wasBlocked = row.getAttribute('data-blocked-by-delink') === '1';
        if (isBlocked) {
          row.setAttribute('data-blocked-by-delink', '1');
          row.style.background = '#eeeeee';
          row.style.opacity = '0.55';
          inp.disabled = true;
          inp.style.background = '#e0e0e0';
          inp.style.borderColor = '#9e9e9e';
          if (status) {
            status.textContent = 'DELINKED';
            status.style.color = '#616161';
            status.title = 'Tray selected for delink';
          }
          if (badge) badge.style.display = 'none';
        } else if (wasBlocked) {
          row.removeAttribute('data-blocked-by-delink');
          row.style.background = '';
          row.style.opacity = '';
          inp.disabled = false;
          inp.style.background = '#fff';
          inp.style.borderColor = '#b2dfdb';
          if (status) { status.textContent = ''; status.title = ''; }
          if (badge) badge.style.display = 'inline-block';
          // Re-run normal validation so the row repaints correctly.
          if ((inp.value || '').trim()) {
            inp.dispatchEvent(new Event('input', { bubbles: true }));
          }
        }
      });
      revalidateSubmit();
    }

    function collectDelinkSelections() {
      var inputs = document.querySelectorAll('.is-reject-delink-scan-input');
      var seen = {};
      var out = [];
      var pool = state.activeTrays || [];
      inputs.forEach(function (inp) {
        var v = (inp.value || '').trim().toUpperCase();
        if (!v || seen[v]) return;
        if (pool.indexOf(v) < 0) return;
        seen[v] = 1;
        out.push(v);
      });
      return out;
    }

    // Delegated handlers for delink slot interactions.
    document.addEventListener('input', function (e) {
      if (!e.target.classList.contains('is-reject-delink-scan-input')) return;
      var inp = e.target;
      var caretEnd = inp.selectionEnd;
      var upper = (inp.value || '').toUpperCase();
      if (upper !== inp.value) {
        inp.value = upper;
        try { inp.setSelectionRange(caretEnd, caretEnd); } catch (_) {}
      }
      validateDelinkInput(inp);
    });
    document.addEventListener('focusin', function (e) {
      if (e.target && e.target.classList &&
          e.target.classList.contains('is-reject-delink-scan-input')) {
        state.activeInput = e.target;
      }
    });
    document.addEventListener('click', function (e) {
      // Clear button on a delink row.
      if (e.target.classList.contains('is-reject-delink-clear-btn')) {
        e.preventDefault();
        var row = e.target.closest('.is-reject-delink-row');
        if (!row) return;
        var inp = row.querySelector('.is-reject-delink-scan-input');
        if (!inp) return;
        inp.value = '';
        paintDelinkRow(inp, { state: 'empty' });
        syncBlockedByDelink();
        inp.focus();
        return;
      }
      // Tap an eligible delink chip → fill the active delink input
      // (or first empty one as a fallback).
      var chip = e.target.closest('.is-reject-delink-chip');
      if (chip) {
        e.preventDefault();
        var trayId = chip.getAttribute('data-tray-id') || '';
        if (!trayId) return;
        var target = state.activeInput;
        if (!target ||
            !target.classList ||
            !target.classList.contains('is-reject-delink-scan-input') ||
            !document.body.contains(target)) {
          var rows = document.querySelectorAll('.is-reject-delink-scan-input');
          target = null;
          for (var i = 0; i < rows.length; i++) {
            if (!(rows[i].value || '').trim()) { target = rows[i]; break; }
          }
          if (!target && rows.length) target = rows[0];
        }
        if (!target) return;
        target.value = trayId.toUpperCase();
        target.dispatchEvent(new Event('input', { bubbles: true }));
        target.focus();
      }
    });

    // Also update on initial page load — revalidate any pre-filled inputs.
    function initPrefilledInputs() {
      var inputs = document.querySelectorAll('.is-reject-tray-scan-input');
      var pending = inputs.length;
      if (!pending) return;
      inputs.forEach(function (inp) {
        // Run the backend validator so colour + status badge reflect any value
        // restored from a previous interaction (tap-to-fill, paste, etc.).
        validateTrayInputBackend(inp, function (result) {
          paintRowState(inp, result);
          pending--;
          if (pending === 0) revalidateSubmit();
        });
      });
    }

    // Hook into renderAllocation to init prefilled state.
    var origRenderAllocation = renderAllocation;
    renderAllocation = function (resp) {
      origRenderAllocation(resp);
      setTimeout(initPrefilledInputs, 0);
    };

    // Collect tray assignments for submission. Reject side only — accept
    // side is informational and not persisted as ``IP_Rejected_TrayScan``.
    function collectTrayAssignments() {
      var rows = elAllocRej ? elAllocRej.querySelectorAll('.is-reject-alloc-row') : [];
      var out = [];
      rows.forEach(function (row) {
        var inp = row.querySelector('.is-reject-tray-scan-input');
        var trayId = inp ? (inp.value || '').trim() : '';
        var rid = parseInt(row.getAttribute('data-reason-id') || '0', 10);
        var qty = parseInt(row.getAttribute('data-expected-qty') || '0', 10);
        if (trayId && rid && qty > 0) {
          out.push({ tray_id: trayId, reason_id: rid, qty: qty });
        }
      });
      return out;
    }

    // ── Submit ──
    elSubmitBtn.addEventListener('click', function () {
      if (elSubmitBtn.disabled) return;
      var fullLot = !!(elFullLotCb && elFullLotCb.checked);
      var remarks = (elRemarks && elRemarks.value || '').trim();
      if (fullLot && !remarks) {
        showError('Remarks are mandatory for Lot Rejection');
        if (elRemarks) elRemarks.focus();
        return;
      }
      var reasons = [];
      elReasonsGrid.querySelectorAll('.is-reject-qty-input').forEach(function (inp) {
        var qty = parseInt(inp.value || '0', 10);
        if (qty > 0) {
          reasons.push({
            reason_id: parseInt(inp.getAttribute('data-reason-id'), 10),
            qty: qty,
          });
        }
      });
      if (!reasons.length) {
        showError('Enter at least one rejection quantity');
        return;
      }
      var totalReject = reasons.reduce(function (a, b) { return a + b.qty; }, 0);
      // If the user typed reasons summing to total qty but did NOT tick
      // the checkbox, treat it as a full lot rejection (parity with the
      // legacy IS flow).
      if (!fullLot && totalReject === state.totalQty) fullLot = true;

      elSubmitBtn.disabled = true;
      elSubmitBtn.textContent = 'Submitting…';

      fetch(SUBMIT_URL, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCookie('csrftoken'),
        },
        body: JSON.stringify({
          lot_id: state.lotId,
          reasons: reasons,
          remarks: remarks,
          full_lot_rejection: fullLot,
          tray_assignments: collectTrayAssignments(),
          delink_tray_ids: collectDelinkSelections(),
        }),
      }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, body: j }; }); })
        .then(function (res) {
          elSubmitBtn.textContent = 'Submit Rejection';
          if (!res.ok || !res.body.success) {
            elSubmitBtn.disabled = false;
            showError(res.body.error || 'Submit failed');
            return;
          }
          // Success — close modal and reload table so server-side state shows.
          closeModal();
          if (window.Swal && typeof window.Swal.fire === 'function') {
            window.Swal.fire({
              icon: 'success',
              title: 'Rejection saved',
              text: 'Rejected ' + res.body.rejected_qty + ' / Accepted ' + res.body.accepted_qty,
              timer: 1800,
              showConfirmButton: false,
            }).then(function () { window.location.reload(); });
          } else {
            window.location.reload();
          }
        }).catch(function (err) {
          console.error('[IS-Reject] submit error', err);
          elSubmitBtn.disabled = false;
          elSubmitBtn.textContent = 'Submit Rejection';
          showError('Network error during submit');
        });
    });
  });
})();

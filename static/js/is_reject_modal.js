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
        elSubmitBtn.disabled = false;
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
      // Refresh active tray chips with the latest server view.
      renderActiveTrayStrip(resp.active_trays || []);
      // Reuse availability summary (Reusable / New / Delink) chip strip.
      renderReuseSummary(resp.reuse_summary || null);
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
      // TOP badge is rendered ONLY on the actual physical top tray
      // (backend marks ``is_top`` exactly once on the surviving top).
      elTrayStrip.innerHTML = trays.map(function (t) {
        var topCls = t.is_top ? ' top' : '';
        return (
          '<span class="is-reject-tray-chip' + topCls + '"' +
            ' data-tray-id="' + escHtml(t.tray_id) + '"' +
            ' role="button" tabindex="0"' +
            ' title="Tap to fill the active scan box"' +
            ' style="cursor:pointer;">' +
            escHtml(t.tray_id) +
            (t.is_top ? ' <span class="badge top" style="background:#ffe0b2;color:#bf360c;font-size:10px;padding:1px 6px;border-radius:8px;margin-left:4px;">TOP</span>' : '') +
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
        var dataAttrs =
          ' data-side="' + sideKey + '"' +
          ' data-slot-index="' + i + '"' +
          ' data-expected-qty="' + (s.qty || 0) + '"' +
          ' data-is-top="' + (s.is_top ? '1' : '0') + '"' +
          (s.reason_id ? ' data-reason-id="' + s.reason_id + '"' : '') +
          (s.candidate_tray_id ? ' data-candidate="' + escHtml(s.candidate_tray_id) + '"' : '');
        return (
          '<div class="is-reject-alloc-row" ' + dataAttrs + '>' +
            '<span class="sno">' + (i + 1) + '</span>' +
            '<span class="tray-id" style="display:flex; align-items:center; gap:6px; flex:1;">' +
              '<input type="text" class="is-reject-tray-scan-input"' +
                ' placeholder="Scan or tap tray…" autocomplete="off" spellcheck="false"' +
                ' style="flex:1; padding:4px 8px; border:1px solid #b2dfdb; border-radius:6px;' +
                ' font-family:monospace; font-size:12px; background:#fff;" />' +
              topBadge + ' ' + reasonBadge +
            '</span>' +
            '<span class="qty">' + s.qty + '</span>' +
            '<span class="badge ' + srcClass + ' is-reject-source-badge" data-source="' + escHtml(s.source || 'New') + '">' + escHtml(s.source || 'New') + '</span>' +
          '</div>'
        );
      }).join('');
    }

    // Track input changes to update 'Scanned' status badge.
    // Delegate handler for dynamically rendered rows.
    document.addEventListener('input', function (e) {
      if (!e.target.classList.contains('is-reject-tray-scan-input')) return;
      var row = e.target.closest('.is-reject-alloc-row');
      if (!row) return;
      var badge = row.querySelector('.is-reject-source-badge');
      if (!badge) return;
      var hasValue = e.target.value.trim().length > 0;
      badge.style.display = hasValue ? 'none' : 'inline-block';
    });
    document.addEventListener('focusin', function (e) {
      if (e.target && e.target.classList &&
          e.target.classList.contains('is-reject-tray-scan-input')) {
        state.activeInput = e.target;
      }
    });

    // Also update on initial page load — revalidate any pre-filled inputs.
    function initPrefilledInputs() {
      var inputs = document.querySelectorAll('.is-reject-tray-scan-input');
      inputs.forEach(function (inp) {
        if (inp.value.trim()) {
          var row = inp.closest('.is-reject-alloc-row');
          if (row) {
            var badge = row.querySelector('.is-reject-source-badge');
            if (badge) badge.style.display = 'none';
          }
        }
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

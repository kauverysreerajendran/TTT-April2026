import sys

fp = r"a:\Workspace\Watchcase\TTT-Jan2026\static\templates\Nickel_Inspection - Zone_two\Nickel_PickTable_zone_two.html"
marker = "{% endblock %} {% endblock content %}"

js_block = """
<!-- NQ Checkbox + Reject Modal JS -->
<script nonce="{{ csp_nonce }}">
(function () {
  var API_BASE = '/nickle_inspection_zone_two/api/';
  var csrf = (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || '';
  function post(url, body) {
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
      body: JSON.stringify(body),
    }).then(function (r) { return r.json(); });
  }
  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.brass-checkbox').forEach(function (cb) {
      cb.addEventListener('change', function () {
        if (!this.checked) return;
        var lotId = this.dataset.lotId;
        var row = this.closest('tr');
        cb.disabled = true;
        post(API_BASE + 'toggle-verified/', { lot_id: lotId })
          .then(function (data) {
            if (data.success) {
              var wrap = cb.parentElement; cb.remove();
              var tick = document.createElement('span');
              tick.style.cssText = 'display:inline-flex;align-items:center;justify-content:center;width:19px;height:19px;border-radius:50%;background:#0c8249;color:white;font-size:14px;font-weight:bold;margin-left:2px;';
              tick.innerHTML = '&#10003;'; wrap.insertBefore(tick, wrap.firstChild);
              if (row) {
                var qCircle = row.querySelector('.d-flex .rounded-circle');
                if (qCircle) qCircle.style.backgroundColor = '#0c8249';
                row.querySelectorAll('.btn-reject-is[disabled], .tray-scan-btn[disabled]').forEach(function (b) { b.removeAttribute('disabled'); });
              }
              setTimeout(function () { location.reload(); }, 500);
            } else { cb.checked = false; cb.disabled = false; alert(data.error || 'Failed to verify'); }
          }).catch(function () { cb.checked = false; cb.disabled = false; alert('Server error'); });
      });
    });
    var overlay = document.getElementById('nickelRejectModalOverlay');
    if (!overlay) return;
    var modalClose = document.getElementById('nickelRejectModalClose');
    var cancelBtn = document.getElementById('nqRejectCancelBtn');
    var reasonsGrid = document.getElementById('nqRejectReasonsGrid');
    var totalQtyDisp = document.getElementById('nqRejectTotalQtyDisplay');
    var remainingDisp = document.getElementById('nqRejectRemainingQtyDisplay');
    var allocSection = document.getElementById('nqTrayAllocationSection');
    var origContainer = document.getElementById('nqOriginalTraysContainer');
    var rejectSlotsCont = document.getElementById('nqRejectSlotsContainer');
    var acceptSlotsCont = document.getElementById('nqAcceptSlotsContainer');
    var delinkSection = document.getElementById('nqDelinkSection');
    var delinkList = document.getElementById('nqDelinkListContainer');
    var reuseInfo = document.getElementById('nqRejectReuseInfo');
    var rejectQtyLabel = document.getElementById('nqRejectTotalQtyLabel');
    var acceptQtyLabel = document.getElementById('nqAcceptTotalQtyLabel');
    var combAccept = document.getElementById('nqCombinedAcceptQty');
    var combReject = document.getElementById('nqCombinedRejectQty');
    var combDelink = document.getElementById('nqCombinedDelinkQty');
    var submitBtn = document.getElementById('nqRejectSubmitBtn');
    var draftBtn = document.getElementById('nqDraftSaveBtn');
    var errDiv = document.getElementById('nqRejectModalError');
    var fullRejCb = document.getElementById('nqFullLotRejectionCb');
    var clearAllBtn = document.getElementById('nqGlobalClearAllBtn');
    var state = { lotId: '', platingStk: '', totalQty: 0, trayCapacity: 20, trayType: '', rejPrefix: 'NB', rejCap: 16, reasons: [], origTrays: [], rejectSlots: [], acceptSlots: [], reuseTrays: [], allocDone: false };
    function closeModal() { overlay.style.display = 'none'; errDiv.textContent = ''; state.allocDone = false; allocSection.style.display = 'none'; }
    if (modalClose) modalClose.addEventListener('click', closeModal);
    if (cancelBtn) cancelBtn.addEventListener('click', closeModal);
    overlay.addEventListener('click', function (e) { if (e.target === overlay) closeModal(); });
    document.querySelectorAll('.tray-scan-btn.btn-reject-is').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var row = btn.closest('tr'); if (!row) return;
        state.lotId = btn.dataset.stockLotId || btn.dataset.lotId || '';
        if (!state.lotId) { var cb2 = row.querySelector('.brass-checkbox'); if (cb2) state.lotId = cb2.dataset.lotId || ''; }
        if (!state.lotId) return;
        state.platingStk = btn.dataset.platingStk || '';
        state.totalQty = parseInt(btn.dataset.totalQty || 0, 10) || 0;
        openRejectModal();
      });
    });
    function openRejectModal() {
      errDiv.textContent = ''; allocSection.style.display = 'none'; state.allocDone = false;
      reasonsGrid.innerHTML = '<span style="color:#888;font-size:13px;">Loading...</span>';
      overlay.style.display = 'flex';
      Promise.all([post(API_BASE + 'action/', { action: 'GET_REASONS' }), post(API_BASE + 'action/', { action: 'GET_TRAYS', lot_id: state.lotId })]).then(function (results) {
        var rData = results[0], tData = results[1];
        if (!rData.success || !tData.success) { reasonsGrid.innerHTML = '<span style="color:red;">Failed to load data</span>'; return; }
        state.reasons = rData.reasons; state.origTrays = tData.trays;
        state.totalQty = tData.total_qty || state.totalQty; state.trayCapacity = tData.tray_capacity || 20;
        state.trayType = tData.tray_type || ''; state.platingStk = tData.plating_stk_no || state.platingStk;
        document.getElementById('nqRejectModalPlatingStk').textContent = state.platingStk;
        document.getElementById('nqRejectModalTotalQty').textContent = state.totalQty;
        totalQtyDisp.textContent = '0'; remainingDisp.textContent = state.totalQty;
        renderReasons();
      }).catch(function () { reasonsGrid.innerHTML = '<span style="color:red;">Server error</span>'; });
    }
    function renderReasons() {
      reasonsGrid.innerHTML = '';
      state.reasons.forEach(function (r) {
        var row = document.createElement('div');
        row.style.cssText = 'display:flex;align-items:center;gap:6px;padding:5px 0;border-bottom:1px solid #f0f0f0;';
        row.innerHTML = '<label style="flex:1;font-size:13px;color:#333;cursor:pointer;"><input type="checkbox" class="nq-reason-cb" data-id="' + r.id + '" style="margin-right:6px;">' + r.rejection_reason + '</label><input type="number" class="nq-reason-qty" min="0" max="' + state.totalQty + '" style="width:64px;border:1px solid #ccc;border-radius:4px;padding:2px 5px;font-size:13px;" placeholder="Qty" data-reason-id="' + r.id + '">';
        reasonsGrid.appendChild(row);
      });
      reasonsGrid.querySelectorAll('.nq-reason-qty').forEach(function (inp) { inp.addEventListener('input', debounce(onReasonQtyChange, 350)); });
      reasonsGrid.querySelectorAll('.nq-reason-cb').forEach(function (cb) {
        cb.addEventListener('change', function () { var qInp = reasonsGrid.querySelector('.nq-reason-qty[data-reason-id="' + cb.dataset.id + '"]'); if (!cb.checked && qInp) { qInp.value = ''; onReasonQtyChange(); } });
      });
      if (fullRejCb) { fullRejCb.onchange = function () { if (fullRejCb.checked) { reasonsGrid.querySelectorAll('.nq-reason-qty').forEach(function (inp) { inp.value = ''; }); var first = reasonsGrid.querySelector('.nq-reason-qty'); if (first) { first.value = state.totalQty; first.dispatchEvent(new Event('input')); } } }; }
    }
    function getTotalRejectQty() { var total = 0; reasonsGrid.querySelectorAll('.nq-reason-qty').forEach(function (inp) { total += parseInt(inp.value, 10) || 0; }); return total; }
    function onReasonQtyChange() {
      var total = getTotalRejectQty(); totalQtyDisp.textContent = total; remainingDisp.textContent = Math.max(0, state.totalQty - total);
      if (total > 0 && total <= state.totalQty) { fetchAllocation(total); } else { allocSection.style.display = 'none'; state.allocDone = false; }
    }
    function fetchAllocation(rejQty) {
      allocSection.style.display = 'none';
      post(API_BASE + 'action/', { action: 'ALLOCATE', lot_id: state.lotId, rejected_qty: rejQty }).then(function (data) {
        if (!data.success) return;
        state.rejectSlots = data.reject_slots; state.acceptSlots = data.accept_slots;
        state.reuseTrays = data.reuse_trays || []; state.rejPrefix = data.rej_prefix || 'NB'; state.rejCap = data.rej_cap || 16;
        renderAllocation(data);
      });
    }
    function renderAllocation(data) {
      origContainer.innerHTML = ''; rejectSlotsCont.innerHTML = ''; acceptSlotsCont.innerHTML = ''; delinkList.innerHTML = '';
      (data.original_trays || []).forEach(function (t) {
        var chip = document.createElement('span');
        chip.style.cssText = 'display:inline-flex;align-items:center;gap:4px;background:#e3f2fd;border:1px solid #90caf9;border-radius:14px;padding:2px 10px;font-size:12px;cursor:pointer;';
        chip.textContent = t.tray_id + ' (' + t.qty + ')'; if (t.is_top) chip.style.borderColor = '#1565c0';
        chip.dataset.trayId = t.tray_id; chip.dataset.qty = t.qty; chip.dataset.isTop = t.is_top ? '1' : '0';
        origContainer.appendChild(chip);
      });
      (data.reject_slots || []).forEach(function (slot, i) {
        var wrap = document.createElement('div'); wrap.style.cssText = 'display:flex;align-items:center;gap:6px;margin-bottom:6px;';
        wrap.innerHTML = '<span style="font-size:11px;color:#888;min-width:24px;">' + (i+1) + '.</span><input class="nq-rej-tray-input" type="text" placeholder="' + state.rejPrefix + 'xxxx" style="flex:1;border:1px solid #ef9a9a;border-radius:4px;padding:3px 6px;font-size:12px;" data-qty="' + slot.qty + '" data-slot-idx="' + i + '">' + '<span style="font-size:12px;color:#c62828;">\u00d7 ' + slot.qty + '</span>';
        rejectSlotsCont.appendChild(wrap);
      });
      (data.accept_slots || []).forEach(function (slot, i) {
        var wrap = document.createElement('div'); wrap.style.cssText = 'display:flex;align-items:center;gap:6px;margin-bottom:6px;';
        wrap.innerHTML = '<span style="font-size:11px;color:#888;min-width:24px;">' + (i+1) + '.</span><input class="nq-acc-tray-input" type="text" placeholder="Tray ID" style="flex:1;border:1px solid #a5d6a7;border-radius:4px;padding:3px 6px;font-size:12px;" data-qty="' + slot.qty + '" data-is-top="' + (slot.is_top ? '1' : '0') + '" data-slot-idx="' + i + '">' + '<span style="font-size:12px;color:#388e3c;">\u00d7 ' + slot.qty + '</span>';
        acceptSlotsCont.appendChild(wrap);
      });
      if ((data.reuse_trays || []).length > 0) {
        reuseInfo.textContent = 'Reusable trays (will be delinked): ' + data.reuse_trays.join(', '); reuseInfo.style.display = '';
        delinkSection.style.display = ''; delinkList.innerHTML = data.reuse_trays.map(function (tid) { return '<span style="background:#fff3e0;border:1px solid #ffe0b2;border-radius:10px;padding:1px 8px;margin:2px;display:inline-block;font-size:11px;">' + tid + '</span>'; }).join('');
        combDelink.textContent = data.reuse_trays.length;
      } else { reuseInfo.style.display = 'none'; delinkSection.style.display = 'none'; combDelink.textContent = '0'; }
      rejectQtyLabel.textContent = data.rejected_qty || 0; acceptQtyLabel.textContent = data.accepted_qty || 0;
      combReject.textContent = data.rejected_qty || 0; combAccept.textContent = data.accepted_qty || 0;
      allocSection.style.display = ''; state.allocDone = true;
      rejectSlotsCont.querySelectorAll('.nq-rej-tray-input').forEach(function (inp) {
        inp.addEventListener('blur', function () { var val = inp.value.trim().toUpperCase(); if (val && !val.startsWith(state.rejPrefix)) { inp.style.borderColor = '#f44336'; errDiv.textContent = 'Reject tray must start with ' + state.rejPrefix; } else { inp.style.borderColor = '#ef9a9a'; errDiv.textContent = ''; } });
      });
    }
    if (clearAllBtn) { clearAllBtn.addEventListener('click', function () { reasonsGrid.querySelectorAll('.nq-reason-qty').forEach(function (i) { i.value = ''; }); reasonsGrid.querySelectorAll('.nq-reason-cb').forEach(function (c) { c.checked = false; }); totalQtyDisp.textContent = '0'; remainingDisp.textContent = state.totalQty; allocSection.style.display = 'none'; state.allocDone = false; }); }
    function buildPayload() {
      var reasonIds = []; reasonsGrid.querySelectorAll('.nq-reason-cb:checked').forEach(function (cb) { reasonIds.push(parseInt(cb.dataset.id, 10)); });
      reasonsGrid.querySelectorAll('.nq-reason-qty').forEach(function (inp) { var rid = parseInt(inp.dataset.reasonId, 10); if ((parseInt(inp.value, 10) || 0) > 0 && !reasonIds.includes(rid)) reasonIds.push(rid); });
      var rejTrays = []; rejectSlotsCont.querySelectorAll('.nq-rej-tray-input').forEach(function (inp) { var tid = inp.value.trim(); var qty = parseInt(inp.dataset.qty, 10) || 0; if (tid && qty > 0) rejTrays.push({ tray_id: tid, qty: qty }); });
      var accTrays = []; acceptSlotsCont.querySelectorAll('.nq-acc-tray-input').forEach(function (inp) { var tid = inp.value.trim(); var qty = parseInt(inp.dataset.qty, 10) || 0; var isTop = inp.dataset.isTop === '1'; if (tid && qty > 0) accTrays.push({ tray_id: tid, qty: qty, is_top: isTop }); });
      return { reason_ids: reasonIds, rejected_qty: getTotalRejectQty(), reject_trays: rejTrays, accept_trays: accTrays, remarks: document.getElementById('nqRejectRemarksInput').value.trim(), lot_id: state.lotId };
    }
    if (submitBtn) {
      submitBtn.addEventListener('click', function () {
        errDiv.textContent = ''; var payload = buildPayload(); payload.action = 'SUBMIT_REJECT';
        if (!payload.reason_ids.length) { errDiv.textContent = 'Select at least one rejection reason.'; return; }
        if (!payload.rejected_qty) { errDiv.textContent = 'Enter rejected quantity.'; return; }
        submitBtn.disabled = true; submitBtn.textContent = 'Saving...';
        post(API_BASE + 'action/', payload).then(function (data) {
          if (data.success) { closeModal(); setTimeout(function () { location.reload(); }, 300); }
          else { errDiv.textContent = data.error || 'Submission failed'; submitBtn.disabled = false; submitBtn.textContent = 'Submit'; }
        }).catch(function () { errDiv.textContent = 'Server error'; submitBtn.disabled = false; submitBtn.textContent = 'Submit'; });
      });
    }
    if (draftBtn) { draftBtn.addEventListener('click', function () { errDiv.textContent = 'Draft save not yet implemented.'; }); }
  });
  function debounce(fn, ms) { var t; return function () { clearTimeout(t); t = setTimeout(fn, ms); }; }
})();
</script>

"""

with open(fp, 'r', encoding='utf-8') as f:
    content = f.read()

idx = content.rfind(marker)
if idx == -1:
    print("ERROR: marker not found")
    sys.exit(1)

new_content = content[:idx] + js_block + marker
with open(fp, 'w', encoding='utf-8') as f:
    f.write(new_content)
print(f"Done. Original={len(content)}, New={len(new_content)}")
print(f"HasJS={('NQ Checkbox' in new_content)}")

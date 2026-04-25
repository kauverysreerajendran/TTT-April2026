/**
 * Nickel QC – Keyboard Shortcuts (mirrors brass_qc_shortcuts.js)
 *
 * Key map:
 *   F2         → Open tray scan for selected / first row
 *   A          → Highlight / select row (focus mode — press Enter to Accept)
 *   R          → Highlight / select row (focus mode — press Enter to Reject)
 *   ↑ / ↓      → Move row selection up / down
 *   ← / →      → Scroll table wrapper horizontally
 *   Enter      → Execute pending action (Accept / Reject) on selected row,
 *                or open view icon if no action pending
 *   Esc        → Close top-most popup (priority stack below)
 *
 * Popup close priority (Esc):
 *   1. nickelRejectModalOverlay
 *   2. trayScanModal (left panel)
 *   3. trayScanModal_DayPlanning (view icon modal)
 *   4. SweetAlert2 (handled natively by Swal)
 *   5. Clear row highlight
 */
(function () {
  "use strict";

  // ─── State ──────────────────────────────────────────────────────────────────
  var _selectedRow   = null;
  var _pendingAction = null;

  // ─── Helpers ────────────────────────────────────────────────────────────────

  function _isTyping() {
    var el = document.activeElement;
    if (!el) return false;
    var tag = el.tagName.toLowerCase();
    return tag === "input" || tag === "textarea" || tag === "select" || el.isContentEditable;
  }

  function _toast(msg, icon) {
    if (window.Swal) {
      Swal.fire({
        toast: true, position: "top-end", icon: icon || "info", title: msg,
        showConfirmButton: false, timer: 2200, timerProgressBar: true,
      });
    }
  }

  // ─── Row selection ───────────────────────────────────────────────────────────

  var ROW_SELECTED_CLASS = "dp-row-action-highlight";

  function _injectStyle() {
    if (document.getElementById("nq-kbd-style")) return;
    var s = document.createElement("style");
    s.id = "nq-kbd-style";
    s.textContent =
      "tr." + ROW_SELECTED_CLASS + " { " +
        "outline: 2px solid #028084 !important; " +
        "outline-offset: -2px !important; " +
      "}";
    document.head.appendChild(s);
  }

  function _getRows() {
    var tbody = document.querySelector("#order-listing tbody");
    if (!tbody) return [];
    return Array.from(tbody.querySelectorAll("tr[data-stock-lot-id]")).filter(function (r) {
      return !r.classList.contains("row-inactive");
    });
  }

  function _selectRow(row) {
    _getRows().forEach(function (r) { r.classList.remove(ROW_SELECTED_CLASS); });
    if (row) {
      row.classList.add(ROW_SELECTED_CLASS);
      row.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
    _selectedRow = row;
  }

  function _moveSelection(delta) {
    var rows = _getRows();
    if (!rows.length) return;
    var idx = _selectedRow ? rows.indexOf(_selectedRow) : -1;
    var next = Math.max(0, Math.min(rows.length - 1, idx + delta));
    _selectRow(rows[next]);
  }

  // ─── Horizontal scroll ───────────────────────────────────────────────────────

  function _scrollHorizontal(dir) {
    var el = document.querySelector(".table-responsive") ||
             document.querySelector(".table-container") ||
             document.querySelector("#order-listing").parentElement;
    if (el) el.scrollLeft += dir * 120;
  }

  // ─── Popup close priority stack ──────────────────────────────────────────────

  function _closeTopPopup() {
    // 1. Nickel QC reject modal overlay
    var nqOverlay = document.getElementById("nickelRejectModalOverlay");
    if (nqOverlay && nqOverlay.style.display !== "none") {
      var cancelBtn = document.getElementById("nqRejectCancelBtn");
      if (cancelBtn) cancelBtn.click(); else nqOverlay.style.display = "none";
      _pendingAction = null; _selectRow(null);
      return true;
    }
    // 2. Left rejection panel (trayScanModal)
    var tsModal = document.getElementById("trayScanModal");
    if (tsModal && tsModal.classList.contains("open")) {
      var closeTs = document.getElementById("closeTrayScanModal");
      if (closeTs) closeTs.click(); else tsModal.classList.remove("open");
      _pendingAction = null; _selectRow(null);
      return true;
    }
    // 3. View icon modal (trayScanModal_DayPlanning)
    var dpModal = document.getElementById("trayScanModal_DayPlanning");
    if (dpModal) {
      var cs = window.getComputedStyle(dpModal);
      if (cs.display !== "none" && cs.visibility !== "hidden") {
        var closeDP = document.getElementById("closeTrayScanModal_DayPlanning");
        if (closeDP) closeDP.click();
        _pendingAction = null; _selectRow(null);
        return true;
      }
    }
    // 4. Clear row highlight and pending action
    if (_selectedRow) {
      _pendingAction = null;
      _selectRow(null);
      return true;
    }
    return false;
  }

  // ─── Action helpers ──────────────────────────────────────────────────────────

  function _confirmAndAccept(acceptBtn) {
    if (!window.Swal) { acceptBtn.click(); return; }
    Swal.fire({
      title: "Accept this lot?",
      icon: "question",
      showCancelButton: true,
      confirmButtonText: "Yes, Accept",
      cancelButtonText: "Cancel",
      confirmButtonColor: "#028084",
      cancelButtonColor: "#6c757d",
      didOpen: function (popup) {
        popup.addEventListener("keydown", function (ev) {
          if (ev.key !== "ArrowLeft" && ev.key !== "ArrowRight") return;
          ev.preventDefault();
          var focused = document.activeElement;
          var confirmBtn = popup.querySelector(".swal2-confirm");
          var cancelBtn2  = popup.querySelector(".swal2-cancel");
          if (focused === confirmBtn) cancelBtn2.focus();
          else confirmBtn.focus();
        });
      },
    }).then(function (result) {
      if (result.isConfirmed) acceptBtn.click();
    });
  }

  function _openScanMode() {
    var row = _selectedRow || _getRows()[0];
    if (!row) { _toast("No lot available to scan.", "info"); return; }
    var pageBtn = document.getElementById("scanButton");
    if (pageBtn) pageBtn.click();
  }

  function _onAcceptKey() {
    var rows = _getRows();
    if (!rows.length) { _toast("No lot available.", "info"); return; }
    if (!_selectedRow) _selectRow(rows[0]);
    _pendingAction = "accept";
    var acceptBtn = _selectedRow.querySelector(".btn-accept-is");
    if (acceptBtn && acceptBtn.disabled) {
      _toast("Accept not available — quantity must be verified first.", "warning");
      _pendingAction = null;
    } else {
      _toast("Accept ready — navigate with ↑↓ then press Enter to confirm.", "success");
    }
  }

  function _onRejectKey() {
    var rows = _getRows();
    if (!rows.length) { _toast("No lot available.", "info"); return; }
    if (!_selectedRow) _selectRow(rows[0]);
    _pendingAction = "reject";
    var rejectBtn = _selectedRow.querySelector(".btn-reject-is");
    if (rejectBtn && rejectBtn.disabled) {
      _toast("Reject not available — quantity must be verified first.", "warning");
      _pendingAction = null;
    } else {
      _toast("Reject ready — navigate with ↑↓ then press Enter to confirm.", "info");
    }
  }

  function _onEnterKey() {
    var row = _selectedRow;
    if (!row) return;
    if (_pendingAction === "accept") {
      var acceptBtn = row.querySelector(".btn-accept-is");
      if (acceptBtn && !acceptBtn.disabled) {
        _pendingAction = null;
        _confirmAndAccept(acceptBtn);
      } else {
        _toast("Accept not available for this row.", "warning");
        _pendingAction = null;
      }
    } else if (_pendingAction === "reject") {
      var rejectBtn = row.querySelector(".btn-reject-is");
      if (rejectBtn && !rejectBtn.disabled) {
        _pendingAction = null;
        rejectBtn.click();
      } else {
        _toast("Reject not available for this row.", "warning");
        _pendingAction = null;
      }
    } else {
      var viewBtn = row.querySelector(".tray-scan-btn-BQ-view");
      if (viewBtn) viewBtn.click();
    }
  }

  // ─── Row click → sync selection ──────────────────────────────────────────────

  function _initRowClickSync() {
    document.addEventListener("click", function (e) {
      var tr = e.target.closest("#order-listing tbody tr[data-stock-lot-id]");
      if (tr) {
        _selectRow(tr);
        _pendingAction = null;
      }
    });
  }

  // ─── Keydown handler ─────────────────────────────────────────────────────────

  function _onKeydown(e) {
    if (e.key === "F2") {
      e.preventDefault();
      _openScanMode();
      return;
    }
    if (e.key === "Escape") {
      e.preventDefault();
      _closeTopPopup();
      return;
    }

    // Suppress page shortcuts when NQ reject modal is open
    var nqOverlay = document.getElementById("nickelRejectModalOverlay");
    if (nqOverlay && nqOverlay.style.display !== "none") return;

    if (_isTyping()) return;

    switch (e.key) {
      case "a":
      case "A":
        e.preventDefault();
        _onAcceptKey();
        break;
      case "r":
      case "R":
      case "d":
      case "D":
        e.preventDefault();
        _onRejectKey();
        break;
      case "ArrowUp":
        e.preventDefault();
        _moveSelection(-1);
        break;
      case "ArrowDown":
        e.preventDefault();
        _moveSelection(1);
        break;
      case "ArrowLeft":
        e.preventDefault();
        _scrollHorizontal(-1);
        break;
      case "ArrowRight":
        e.preventDefault();
        _scrollHorizontal(1);
        break;
      case "Enter":
        e.preventDefault();
        _onEnterKey();
        break;
    }
  }

  // ─── bfcache restore: close all modals ───────────────────────────────────────

  window.addEventListener("pageshow", function (e) {
    if (!e.persisted) return;
    var nqOverlay = document.getElementById("nickelRejectModalOverlay");
    if (nqOverlay) nqOverlay.style.display = "none";
    var tsm = document.getElementById("trayScanModal");
    if (tsm) tsm.classList.remove("open");
    var dpm = document.getElementById("trayScanModal_DayPlanning");
    if (dpm) { dpm.classList.remove("open"); }
  });

  // ─── Boot ────────────────────────────────────────────────────────────────────

  document.addEventListener("DOMContentLoaded", function () {
    _injectStyle();
    _initRowClickSync();
    document.addEventListener("keydown", _onKeydown);
  });

})();

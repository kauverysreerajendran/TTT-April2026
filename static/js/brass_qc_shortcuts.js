/**
 * Brass QC – Keyboard Shortcuts
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
 */
(function () {
  "use strict";

  // ─── State ──────────────────────────────────────────────────────────────────
  var _selectedRow  = null;   // currently highlighted <tr>
  var _pendingAction = null;  // "accept" | "reject" | null

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

  // ─── Row selection (reuse existing class, no duplicate highlight system) ────

  // Reuse the dp-row-action-highlight class (already defined by the page).
  // We add a secondary CSS outline only for keyboard-selected rows.
  var ROW_SELECTED_CLASS = "dp-row-action-highlight";

  function _injectStyle() {
    if (document.getElementById("bq-kbd-style")) return;
    var s = document.createElement("style");
    s.id = "bq-kbd-style";
    // Outline only — do not override the page's existing dp-row-action-highlight background
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
    // Try the table-responsive wrapper first, then fall back to table container
    var el = document.querySelector(".table-responsive") ||
             document.querySelector(".table-container") ||
             document.querySelector("#order-listing").parentElement;
    if (el) el.scrollLeft += dir * 120;
  }

  // ─── Popup close priority stack ──────────────────────────────────────────────

  function _closeTopPopup() {
    // 1. Brass QC reject modal overlay
    var bro = document.getElementById("brassRejectModalOverlay");
    if (bro && bro.style.display !== "none") {
      var cancelBtn = document.getElementById("rejectCancelBtn");
      if (cancelBtn) cancelBtn.click(); else bro.style.display = "none";
      return true;
    }
    // 2. Left rejection panel (trayScanModal)
    var tsModal = document.getElementById("trayScanModal");
    if (tsModal && tsModal.classList.contains("open")) {
      var closeTs = document.getElementById("closeTrayScanModal");
      if (closeTs) closeTs.click(); else tsModal.classList.remove("open");
      return true;
    }
    // 3. Day Planning view modal
    var dpModal = document.getElementById("trayScanModal_DayPlanning");
    if (dpModal) {
      var cs = window.getComputedStyle(dpModal);
      if (cs.display !== "none" && cs.visibility !== "hidden") {
        var closeDP = document.getElementById("closeTrayScanModal_DayPlanning");
        if (closeDP) closeDP.click();
        return true;
      }
    }
    // 4. Accept popup
    var acceptPop = document.getElementById("newPopupModal");
    if (acceptPop && acceptPop.classList.contains("open")) {
      var closeAcc = document.getElementById("closeNewPopupModal");
      if (closeAcc) closeAcc.click(); else acceptPop.classList.remove("open");
      return true;
    }
    // 5. Hold remark modal
    var holdModal = document.getElementById("holdRemarkModal");
    if (holdModal && holdModal.style.display === "flex") { holdModal.style.display = "none"; return true; }
    // 6. Clear row highlight and pending action
    if (_selectedRow) {
      _pendingAction = null;
      _selectRow(null);
      return true;
    }
    return false;
  }

  // ─── Action helpers ──────────────────────────────────────────────────────────

  /**
   * Show a SweetAlert2 confirm with Cancel as the default focused button.
   * Left / Right arrows swap focus between Cancel and Accept.
   * Only proceeds to acceptBtn.click() if the operator confirms.
   */
  function _confirmAndAccept(acceptBtn) {
    if (!window.Swal) { acceptBtn.click(); return; }
    Swal.fire({
      title: "Accept this lot?",
      icon: "question",
      showCancelButton: true,
      confirmButtonText: "Accept",
      cancelButtonText: "Cancel",
      confirmButtonColor: "#028084",
      cancelButtonColor: "#6c757d",
      focusCancel: true,   // Cancel is the default-focused (safe default)
      reverseButtons: false,
      didOpen: function (popup) {
        // Left / Right arrows toggle focus between the two buttons
        popup.addEventListener("keydown", function (ev) {
          if (ev.key !== "ArrowLeft" && ev.key !== "ArrowRight") return;
          ev.preventDefault();
          var focused = document.activeElement;
          var confirmBtn = popup.querySelector(".swal2-confirm");
          var cancelBtn  = popup.querySelector(".swal2-cancel");
          if (focused === confirmBtn) cancelBtn.focus();
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

  /**
   * A key pressed:
   *   - If no row highlighted → highlight first row, set pendingAction="accept"
   *   - If row already highlighted → set pendingAction="accept", show hint
   */
  function _onAcceptKey() {
    var rows = _getRows();
    if (!rows.length) { _toast("No lot available.", "info"); return; }
    if (!_selectedRow) {
      _selectRow(rows[0]);
    }
    _pendingAction = "accept";
    var acceptBtn = _selectedRow.querySelector(".btn-accept-is");
    if (acceptBtn && acceptBtn.disabled) {
      _toast("Accept not available — quantity must be verified first.", "warning");
      _pendingAction = null;
    } else {
      _toast("Accept ready — navigate with ↑↓ then press Enter to confirm.", "success");
    }
  }

  /**
   * R key pressed:
   *   - If no row highlighted → highlight first row, set pendingAction="reject"
   *   - If row already highlighted → set pendingAction="reject", show hint
   */
  function _onRejectKey() {
    var rows = _getRows();
    if (!rows.length) { _toast("No lot available.", "info"); return; }
    if (!_selectedRow) {
      _selectRow(rows[0]);
    }
    _pendingAction = "reject";
    var rejectBtn = _selectedRow.querySelector(".btn-reject-is");
    if (rejectBtn && rejectBtn.disabled) {
      _toast("Reject not available — quantity must be verified first.", "warning");
      _pendingAction = null;
    } else {
      _toast("Reject ready — navigate with ↑↓ then press Enter to confirm.", "info");
    }
  }

  /**
   * Enter key:
   *   - If pendingAction="accept" → click the Accept button on selected row
   *   - If pendingAction="reject" → click the Reject button on selected row
   *   - Otherwise → click the view icon on selected row
   */
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
      // Default: open view icon
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
    // F2 — always intercept
    if (e.key === "F2") {
      e.preventDefault();
      _openScanMode();
      return;
    }
    // Escape — always intercept
    if (e.key === "Escape") {
      e.preventDefault();
      _closeTopPopup();
      return;
    }

    // Suppress page shortcuts when reject modal is open
    var bro = document.getElementById("brassRejectModalOverlay");
    if (bro && bro.style.display !== "none") return;

    // Skip all other shortcuts when user is typing
    if (_isTyping()) return;

    switch (e.key) {
      case "a":
      case "A":
        e.preventDefault();
        _onAcceptKey();
        break;
      case "r":
      case "R":
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
    var bro = document.getElementById("brassRejectModalOverlay");
    if (bro) bro.style.display = "none";
    var tsm = document.getElementById("trayScanModal");
    if (tsm) tsm.classList.remove("open");
    var dpm = document.getElementById("trayScanModal_DayPlanning");
    if (dpm) { dpm.style.display = "none"; dpm.classList.remove("open"); }
    var ap = document.getElementById("newPopupModal");
    if (ap) ap.classList.remove("open");
    var hm = document.getElementById("holdRemarkModal");
    if (hm) hm.style.display = "none";
  });

  // ─── Boot ────────────────────────────────────────────────────────────────────

  document.addEventListener("DOMContentLoaded", function () {
    _injectStyle();
    _initRowClickSync();
    document.addEventListener("keydown", _onKeydown);
  });

})();

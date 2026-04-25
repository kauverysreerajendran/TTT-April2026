/**
 * Input Screening – Keyboard Shortcuts
 *
 * Shortcuts only fire on the IS Pick Table page.
 * Guards:
 *   - Ignored when focus is inside input / textarea / select / contenteditable
 *   - F1 is always intercepted (prevents browser Help dialog)
 *
 * Key map:
 *   F2     → Display "Please Scan" hint and open tray verification modal for selected / highlighted row (or first row if none selected)
 *   A      → accept selected / highlighted lot
 *   R      → open reject window for selected / highlighted lot
 *   Esc    → close top-most open popup (priority order below)
 *   ↑ / ↓  → move row selection up / down in the pick table
 *   Enter  → open tray-verification modal for selected row
 */
(function () {
  "use strict";

  // ─── State ─────────────────────────────────────────────────────────────────
  var _selectedRow = null; // currently keyboard-selected <tr>

  // ─── Helpers ───────────────────────────────────────────────────────────────

  /** Returns true when the user is actively typing in a form field. */
  function _isTyping() {
    var el = document.activeElement;
    if (!el) return false;
    var tag = el.tagName.toLowerCase();
    return (
      tag === "input" ||
      tag === "textarea" ||
      tag === "select" ||
      el.isContentEditable
    );
  }

  /** Lightweight toast – falls back to nothing if Swal is absent. */
  function _toast(msg, icon) {
    if (window.Swal) {
      Swal.fire({
        toast: true,
        position: "top-end",
        icon: icon || "warning",
        title: msg,
        showConfirmButton: false,
        timer: 2200,
        timerProgressBar: true,
      });
    }
  }

  // ─── Row selection ─────────────────────────────────────────────────────────

  var ROW_SELECTED_CLASS = "is-kbd-selected";

  /** Inject a small CSS rule for the selection highlight once. */
  function _injectSelectionStyle() {
    if (document.getElementById("is-kbd-selection-style")) return;
    var style = document.createElement("style");
    style.id = "is-kbd-selection-style";
    // Apply highlight to both the row and its cells so the background
    // shows even when individual <td>s have their own background-color
    // (e.g. .row-inactive-blur). Outline on the row gives the border
    // effect and works regardless of cell-level styling.
    // Outline only — avoids conflict with existing row background colours
    style.textContent =
      "tr." + ROW_SELECTED_CLASS +
      " { outline: 2px solid #028084 !important;" +
      " outline-offset: -2px !important; }";
    document.head.appendChild(style);
  }

  /** Return all visible, non-hold, non-header table rows. */
  function _getRows() {
    var tbody = document.querySelector("#order-listing tbody");
    if (!tbody) return [];
    return Array.from(tbody.querySelectorAll("tr[data-stock-lot-id], tr[data-lot-id]")).filter(
      function (r) {
        return !r.classList.contains("row-inactive");
      }
    );
  }

  /** Set the visually-selected row. Pass null to deselect all. */
  function _selectRow(row) {
    _getRows().forEach(function (r) {
      r.classList.remove(ROW_SELECTED_CLASS);
    });
    if (row) {
      row.classList.add(ROW_SELECTED_CLASS);
      row.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
    _selectedRow = row;
  }

  /** Move selection by +1 (down) or -1 (up). */
  function _moveSelection(delta) {
    var rows = _getRows();
    if (!rows.length) return;
    var idx = _selectedRow ? rows.indexOf(_selectedRow) : -1;
    var next = idx + delta;
    if (next < 0) next = 0;
    if (next >= rows.length) next = rows.length - 1;
    _selectRow(rows[next]);
  }

  // ─── Popup priority stack ──────────────────────────────────────────────────

  /**
   * Close the top-most visible popup and return true if something was closed.
   * Priority (highest first):
   *   1. Tray Verification Modal (trayVerificationModal)
   *   2. IS Reject Modal (isRejectModal)
   *   3. Rejection Window left panel (trayScanModal)
   *   4. Day Planning view modal (trayScanModal_DayPlanning)
   *   5. Accept popup (newPopupModal)
   *   6. Hold remark modal (holdRemarkModal)
   *   7. Row highlight / selection
   */
  function _closeTopPopup() {
    // 1. Tray Verification Modal
    var tvm = document.getElementById("trayVerificationModal");
    if (tvm && tvm.style.display !== "none") {
      if (typeof window.tvmClose === "function") {
        window.tvmClose();
      } else {
        tvm.style.display = "none";
      }
      return true;
    }

    // 2. IS Reject Modal
    var isrm = document.getElementById("isRejectModal");
    if (isrm && isrm.classList.contains("open")) {
      var cancelBtn = document.getElementById("isrm-cancel-btn");
      if (cancelBtn) cancelBtn.click();
      else isrm.classList.remove("open");
      return true;
    }

    // 3. Rejection Window (left panel)
    var tsModal = document.getElementById("trayScanModal");
    if (tsModal && tsModal.classList.contains("open")) {
      var closeTs = document.getElementById("closeTrayScanModal");
      if (closeTs) closeTs.click();
      else tsModal.classList.remove("open");
      return true;
    }

    // 4. Day Planning view modal
    var dpModal = document.getElementById("trayScanModal_DayPlanning");
    if (dpModal) {
      var dpComputed = window.getComputedStyle(dpModal);
      if (dpComputed.display !== "none" && dpComputed.visibility !== "hidden") {
        var closeDP = document.getElementById("closeTrayScanModal_DayPlanning");
        if (closeDP) closeDP.click();
        return true;
      }
    }

    // 5. Accept popup
    var acceptPop = document.getElementById("newPopupModal");
    if (acceptPop && acceptPop.classList.contains("open")) {
      var closeAcc = document.getElementById("closeNewPopupModal");
      if (closeAcc) closeAcc.click();
      else acceptPop.classList.remove("open");
      return true;
    }

    // 6. Hold remark modal
    var holdModal = document.getElementById("holdRemarkModal");
    if (holdModal && holdModal.style.display === "flex") {
      holdModal.style.display = "none";
      return true;
    }

    // 7. Row highlight / selection
    if (_selectedRow) {
      _selectRow(null);
      if (typeof window.restoreRowPosition === "function") {
        window.restoreRowPosition();
      }
      return true;
    }

    return false;
  }

  // ─── Action helpers ────────────────────────────────────────────────────────

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

  /** Open the tray verification scan for the selected row (or first row). */
  function _openScanMode() {
    // If a row is selected, open TVM for that lot
    var row = _selectedRow || _getRows()[0];
    if (!row) {
      _toast("No lot available to scan.", "info");
      return;
    }
    var viewBtn = row.querySelector(".tray-scan-btn-DayPlanning-view");
    if (viewBtn) {
      viewBtn.click();
    } else {
      // Fallback: click the page-level scan button
      var pageBtn = document.getElementById("scanButton");
      if (pageBtn) pageBtn.click();
    }
  }

  /** Trigger the Accept button on the selected / highlighted row. */
  function _openAcceptConfirm() {
    var row = _selectedRow || _getRows()[0];
    if (!row) {
      _toast("No lot available.", "info");
      return;
    }
    var acceptBtn = row.querySelector(".btn-accept-is");
    if (!acceptBtn) {
      _toast("Accept button not found for this row.", "error");
      return;
    }
    if (acceptBtn.disabled) {
      _toast(
        "Accept is not available — all trays must be verified first.",
        "warning"
      );
      return;
    }
    // Show confirm dialog with Cancel as default (safe) — arrow keys switch buttons
    _confirmAndAccept(acceptBtn);
  }

  /** Trigger the Reject button on the selected / highlighted row. */
  function _openRejectWindow() {
    var row = _selectedRow || _getRows()[0];
    if (!row) {
      _toast("No lot available.", "info");
      return;
    }
    var rejectBtn = row.querySelector(".btn-reject-is");
    if (!rejectBtn) {
      _toast("Reject button not found for this row.", "error");
      return;
    }
    if (rejectBtn.disabled) {
      _toast(
        "Reject is not available — all trays must be verified first.",
        "warning"
      );
      return;
    }
    rejectBtn.click();
  }

  /** Open tray verification modal for selected row (Enter key). */
  function _openSelectedRowDetail() {
    var row = _selectedRow;
    if (!row) return;
    var viewBtn = row.querySelector(".tray-scan-btn-DayPlanning-view, .tray-scan-btn-BQ-view, .tray-scan-btn-Jig");
    if (viewBtn) viewBtn.click();
  }

  // ─── Row click → sync selection ───────────────────────────────────────────

  /** Keep _selectedRow in sync when user clicks a table row directly. */
  function _initRowClickSync() {
    document.addEventListener("click", function (e) {
      var tr = e.target.closest("#order-listing tbody tr[data-stock-lot-id], #order-listing tbody tr[data-lot-id]");
      if (tr) _selectRow(tr);
    });
  }

  // ─── Scan-status indicator helpers ────────────────────────────────────────

  var _pleaseScanTimer = null;

  /** Show the inline "PLEASE SCAN" hint next to the Scan button. */
  function _showPleaseScan() {
    var span = document.getElementById("scanStatusMessage");
    if (!span) return;
    span.style.display = "inline-block";
    if (_pleaseScanTimer) clearTimeout(_pleaseScanTimer);
    _pleaseScanTimer = setTimeout(function () {
      span.style.display = "none";
    }, 4000);
  }

  /** Hide the inline scan hint (called once a real scan modal opens). */
  function _hidePleaseScan() {
    var span = document.getElementById("scanStatusMessage");
    if (span) span.style.display = "none";
    if (_pleaseScanTimer) {
      clearTimeout(_pleaseScanTimer);
      _pleaseScanTimer = null;
    }
  }

  // ─── Global keydown handler ────────────────────────────────────────────────

  function _onKeydown(e) {
    // F1 — always intercept, regardless of focus
    if (e.key === "F1") {
      e.preventDefault();
      // If the selected (or first) row already has all trays verified,
      // just highlight it so the operator can hit A/R immediately.
      var _f1row = _selectedRow || _getRows()[0];
      if (_f1row) {
        var _f1accept = _f1row.querySelector(".btn-accept-is");
        if (_f1accept && !_f1accept.disabled) {
          _selectRow(_f1row);
          _toast("All trays verified \u2013 press A to Accept or R to Reject", "success");
          return;
        }
      }
      // Otherwise open the Tray Verification Modal for the selected/first row.
      _openScanMode();
      return;
    }

    // Escape — always intercept, regardless of focus
    if (e.key === "Escape") {
      e.preventDefault();
      _closeTopPopup();
      return;
    }

    // ── ERR1 GUARD: when the IS Reject Modal is open, suppress every other
    // page-level shortcut (Enter, A, R, ArrowUp/Down).  During a tray scan
    // the input may briefly lose focus between auto-validate cycles or the
    // hardware scanner may emit a trailing Enter — letting those keys reach
    // the row handler would silently open the eye-icon view modal
    // (trayScanModal_DayPlanning) behind the reject modal.
    var _isrm = document.getElementById("isRejectModal");
    if (_isrm && _isrm.classList.contains("open")) return;

    // All other shortcuts: skip when user is typing
    if (_isTyping()) return;

    switch (e.key) {
      case "a":
      case "A":
        e.preventDefault();
        _openAcceptConfirm();
        break;

      case "r":
      case "R":
        e.preventDefault();
        _openRejectWindow();
        break;

      case "ArrowUp":
        e.preventDefault();
        _moveSelection(-1);
        break;

      case "ArrowDown":
        e.preventDefault();
        _moveSelection(1);
        break;

      case "Enter":
        e.preventDefault();
        _openSelectedRowDetail();
        break;
    }
  }

  // ─── Boot ──────────────────────────────────────────────────────────────────

  document.addEventListener("DOMContentLoaded", function () {
    _injectSelectionStyle();
    _initRowClickSync();
    document.addEventListener("keydown", _onKeydown);

    // Page-level Scan button → show inline "PLEASE SCAN" indicator.
    var scanBtn = document.getElementById("scanButton");
    if (scanBtn) {
      scanBtn.addEventListener("click", _showPleaseScan);
    }

    // Capture-phase guard (ERR4): when the IS Reject Modal is open, block
    // any click that would open the eye-icon view modal in the background
    // (hardware scanners can emit a stray Enter that bubbles through to the
    // delegated handler in inputscreening_picktable.js). We also re-focus
    // the active scan input so the operator can keep scanning.
    document.addEventListener(
      "click",
      function (e) {
        var modal = document.getElementById("isRejectModal");
        if (!modal || !modal.classList.contains("open")) return;
        var viewBtn = e.target.closest(".tray-scan-btn-DayPlanning-view");
        if (!viewBtn) return;
        e.preventDefault();
        e.stopPropagation();
        if (typeof e.stopImmediatePropagation === "function") {
          e.stopImmediatePropagation();
        }
        var inp = modal.querySelector(
          ".isrm-scan-input:not([readonly]):not([disabled])"
        );
        if (inp) inp.focus();
      },
      true
    );

    // Expose tvmClose globally (may be needed by Esc handler before tvmClose
    // is set by inputscreening_picktable.js).  The picktable script overwrites
    // this with the real implementation later; this is only a safe fallback.
    if (!window.tvmClose) {
      window.tvmClose = function () {
        var m = document.getElementById("trayVerificationModal");
        if (m) m.style.display = "none";
      };
    }
  });
})();

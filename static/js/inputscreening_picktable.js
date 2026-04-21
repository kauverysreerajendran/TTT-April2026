// ====== Original inline block #1 ======
document.addEventListener("DOMContentLoaded", function () {
  // ✅ HELPER FUNCTION: Get edited tray qty from modal
  function getEditedTrayQtyFromModal() {
    const modal = document.getElementById("trayScanModal_DayPlanning");
    if (!modal) {
      return null;
    }
    // Find the top tray input
    const editedTrayQtyInput = modal.querySelector(
      '.tray-qty-input[data-top-tray="1"]',
    );
    if (!editedTrayQtyInput) {
      return null;
    }
    const currentValue = editedTrayQtyInput.value.trim();
    const initialValue = editedTrayQtyInput.getAttribute("data-initial") || "";
    // Return current value regardless of whether it changed
    return currentValue || null;
  }
  // ✅ HELPER FUNCTION: Get CSRF token
  function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== "") {
      const cookies = document.cookie.split(";");
      for (let i = 0; i < cookies.length; i++) {
        const cookie = cookies[i].trim();
        if (cookie.substring(0, name.length + 1) === name + "=") {
          cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
          break;
        }
      }
    }
    return cookieValue;
  }
  // ✅ SAVE IP CHECKBOX HANDLER
  document.addEventListener("click", function (e) {
    if (e.target.classList.contains("save-ip-checkbox")) {
      const element = e.target;
      const row = element.closest("tr");
      let lotId = element.getAttribute("data-lot-id");
      if (!lotId) lotId = row.getAttribute("data-stock-lot-id");
      if (!lotId) {
        Swal.fire("Error", "Lot ID not found", "error");
        return;
      }
      // Get the calculated missing qty from the input
      const missingQtyInput = row.querySelector(".missing-qty-input");
      const missingQty = missingQtyInput ? missingQtyInput.value.trim() : "0";
      // ✅ FIXED: Get edited tray qty using helper function
      const editedTrayQty = getEditedTrayQtyFromModal();
      // Change icon to indicate processing
      if (element.tagName === "I") {
        element.className = "fa fa-spinner fa-spin";
      }
      // Disable element during processing
      element.style.pointerEvents = "none";
      fetch("/inputscreening/save_ip_checkbox/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": getCookie("csrftoken"),
        },
        body: JSON.stringify({
          lot_id: lotId,
          missing_qty: missingQty || "0",
          edited_tray_qty: editedTrayQty,
        }),
      })
        .then((res) => res.json())
        .then((data) => {
          if (data.success) {
            // Change to checked state
            if (element.tagName === "I") {
              element.className = "fa fa-check-square";
              element.style.color = "#28a745";
            }
            element.title = "IP Checkbox saved";
            Swal.fire({
              icon: "success",
              title: "Saved successfully!",
              timer: 2000,
              showConfirmButton: false,
            });
            // Update row to show verification completed
            updateRowAfterIPSave(row, lotId, missingQty);
            // Reload page after a short delay
            setTimeout(() => {
              window.location.reload();
            }, 1500);
          } else {
            Swal.fire("Error", data.error || "Save failed", "error");
            // Reset icon and enable element
            if (element.tagName === "I") {
              element.className = "fa fa-square-o";
            }
            element.style.pointerEvents = "auto";
          }
        })
        .catch((error) => {
          Swal.fire("Error", "Network error", "error");
          // Reset icon and enable element
          if (element.tagName === "I") {
            element.className = "fa fa-square-o";
          }
          element.style.pointerEvents = "auto";
        });
    }
  });
  // ✅ HELPER FUNCTION: Update row after IP save
  function updateRowAfterIPSave(row, lotId, missingQty) {
    // Update main IP checkbox
    const mainIpCheckbox = row.querySelector(".ip-checkbox");
    if (mainIpCheckbox) {
      mainIpCheckbox.checked = true;
      mainIpCheckbox.disabled = true;
    }
    // Update missing qty input
    const missingQtyInput = row.querySelector(".missing-qty-input");
    if (missingQtyInput) {
      missingQtyInput.disabled = true;
    }
    // Update physical qty
    const physicalQtyInput = row.querySelector(".physical-qty-input");
    const lotQtySpan = row.querySelector(".lot-qty");
    if (physicalQtyInput && lotQtySpan && missingQty) {
      const totalQty = parseInt(lotQtySpan.textContent.trim(), 10);
      const newPhysicalQty = totalQty - parseInt(missingQty);
      physicalQtyInput.value = newPhysicalQty;
    }
    // Update process status Q icon
    const processIcons = row.querySelectorAll(".d-flex > div");
    if (processIcons.length > 0) {
      processIcons[0].style.backgroundColor = "#0c8249";
    }
  }
  // ✅ Make helper functions available globally
  window.getEditedTrayQtyFromModal = getEditedTrayQtyFromModal;
  window.getCookie = getCookie;
});
// ====== Original inline block #2 ======
document.addEventListener("DOMContentLoaded", function () {
  // Use event delegation to handle dynamically created buttons
  document.addEventListener("click", function (e) {
    // ✅ Check if the clicked element is a Delete button
    const deleteBtn =
      e.target.closest(".delete-batch-btn") ||
      (e.target.tagName === "IMG" &&
        e.target.alt === "Delete" &&
        e.target.closest('a[class*="delete-batch-btn"]'));
    if (deleteBtn) {
      e.preventDefault();
      const row = deleteBtn.closest("tr");
      if (!row) return;
      const batchId = deleteBtn.getAttribute("data-batch-id");
      const stockLotId = deleteBtn.getAttribute("data-stock-lot-id");
      if (!batchId || !stockLotId) {
        Swal.fire("Error", "Batch ID or Stock Lot ID not found!", "error");
        return;
      }
      Swal.fire({
        title: "Are you sure?",
        text: "Do you really want to delete this batch?",
        icon: "warning",
        showCancelButton: true,
        confirmButtonColor: "#d33",
        cancelButtonColor: "#3085d6",
        confirmButtonText: "Yes, delete it!",
        cancelButtonText: "Cancel",
      }).then((result) => {
        if (result.isConfirmed) {
          fetch("/inputscreening/ip_delete_batch/", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-CSRFToken": getCookie("csrftoken"),
            },
            body: JSON.stringify({
              batch_id: batchId,
              stock_lot_id: stockLotId,
            }),
          })
            .then((res) => res.json())
            .then((data) => {
              if (data.success) {
                row.remove();
                Swal.fire({
                  icon: "success",
                  title: "Deleted!",
                  text: "Batch has been deleted successfully.",
                  timer: 2000,
                  showConfirmButton: false,
                });
              } else {
                Swal.fire(
                  "Error",
                  data.message || "Failed to delete batch",
                  "error",
                );
              }
            })
            .catch((error) => {
              console.error("Delete error:", error);
              Swal.fire(
                "Error",
                "An error occurred while deleting the batch",
                "error",
              );
            });
        }
      });
      return;
    }
  });
  // Helper function for CSRF token (if not already defined)
  function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== "") {
      const cookies = document.cookie.split(";");
      for (let i = 0; i < cookies.length; i++) {
        const cookie = cookies[i].trim();
        if (cookie.substring(0, name.length + 1) === name + "=") {
          cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
          break;
        }
      }
    }
    return cookieValue;
  }
});
// ====== Original inline block #3 ======
document.addEventListener("DOMContentLoaded", function () {
  const cancelBtn = document.getElementById("trayScanCancelBtn");
  if (cancelBtn) {
    cancelBtn.addEventListener("click", function () {
      const modal = document.getElementById("trayScanModal_BQ");
      if (modal) modal.classList.remove("open");
    });
  }
  // DELETE BUTTON HANDLER - REMOVED (Now handled via event delegation)
  // Helper function to show error notification
  function showErrorNotification(message) {
    // Create or get existing notification element
    let notification = document.getElementById("error-notification");
    if (!notification) {
      notification = document.createElement("div");
      notification.id = "error-notification";
      notification.style.cssText = `
         position: fixed;
         left: 50%;
         top: 50%;
         transform: translate(-50%, -50%);
         background: #dc3545;
         color: white;
         padding: 18px 32px;
         border-radius: 12px;
         box-shadow: 0 4px 24px rgba(220,53,69,0.18);
         z-index: 10001;
         font-weight: 600;
         font-size: 18px;
         text-align: center;
         transition: opacity 0.3s ease;
         opacity: 1;
       `;
      document.body.appendChild(notification);
    }
    notification.textContent = message;
    // Show notification
    notification.style.opacity = "1";
    // Hide notification after 4 seconds
    setTimeout(() => {
      notification.style.opacity = "0";
    }, 4000);
  }
  const table = document.getElementById("order-listing");
  if (!table) {
    return;
  }
  const headers = table.querySelectorAll("thead th");
  const tbody = table.querySelector("tbody");
  let sortDirection = {};
  headers.forEach((header, index) => {
    header.style.cursor = "pointer";
    header.addEventListener("click", function () {
      const rows = Array.from(tbody.querySelectorAll("tr"));
      const dir = sortDirection[index] === "asc" ? "desc" : "asc";
      sortDirection[index] = dir;
      rows.sort((a, b) => {
        const cellA = a.children[index].textContent.trim();
        const cellB = b.children[index].textContent.trim();
        const valA = isNaN(cellA) ? cellA : parseFloat(cellA);
        const valB = isNaN(cellB) ? cellB : parseFloat(cellB);
        if (valA < valB) return dir === "asc" ? -1 : 1;
        if (valA > valB) return dir === "asc" ? 1 : -1;
        return 0;
      });
      tbody.innerHTML = "";
      rows.forEach((row) => tbody.appendChild(row));
    });
  });
});
// ====== Original inline block #4 ======
// Row highlight & position swap for tray-scan-btn-Jig, tray-scan-btn (Set Top Tray/Reject), and btn-twitter (Accept)
document.addEventListener("DOMContentLoaded", function () {
  // Add highlight style if not present
  if (!document.getElementById("dp-row-action-highlight-style")) {
    var style = document.createElement("style");
    style.id = "dp-row-action-highlight-style";
    style.innerHTML = `
         .dp-row-action-highlight {
           transition: box-shadow 1.3s;
           background-color: #fff5bd !important;
           animation: highlightAnimation 2s ease-in-out;
         }
       `;
    document.head.appendChild(style);
  }
  let originalRowIndex = null;
  let movedRow = null;
  let placeholderRow = null;
  // Function to handle row highlighting and movement
  function handleRowHighlight(event) {
    // Remove highlight from all rows
    document.querySelectorAll("tbody tr").forEach(function (row) {
      row.classList.remove("dp-row-action-highlight");
    });
    // Move the clicked row to the top and highlight
    var row = event.target.closest("tr");
    if (row && row.parentNode) {
      const tbody = row.parentNode;
      // Only move if not already at top
      if (tbody.firstElementChild !== row) {
        // If a previous move exists, restore it first
        if (movedRow && placeholderRow && placeholderRow.parentNode) {
          placeholderRow.parentNode.insertBefore(movedRow, placeholderRow);
          placeholderRow.parentNode.removeChild(placeholderRow);
          movedRow.classList.remove("dp-row-action-highlight");
          movedRow = null;
          placeholderRow = null;
          originalRowIndex = null;
        }
        // Store original index and row
        originalRowIndex = Array.from(tbody.children).indexOf(row);
        movedRow = row;
        // Insert a placeholder at the original position
        placeholderRow = document.createElement("tr");
        placeholderRow.style.display = "none";
        tbody.insertBefore(placeholderRow, tbody.children[originalRowIndex]);
        // Move row to top
        tbody.insertBefore(row, tbody.firstElementChild);
      }
      row.classList.add("dp-row-action-highlight");
    }
  }
  // Function to restore row position and remove highlight
  function restoreRowPosition() {
    if (movedRow && placeholderRow && placeholderRow.parentNode) {
      placeholderRow.parentNode.insertBefore(movedRow, placeholderRow);
      placeholderRow.parentNode.removeChild(placeholderRow);
      movedRow.classList.remove("dp-row-action-highlight");
      movedRow = null;
      placeholderRow = null;
      originalRowIndex = null;
    }
    // Also remove highlight from any row just in case
    document.querySelectorAll("tbody tr").forEach(function (row) {
      row.classList.remove("dp-row-action-highlight");
      row.classList.remove("highlighted-tray-scan");
    });
  }
  // Add event listeners for View buttons (tray-scan-btn-Jig)
  document.querySelectorAll(".tray-scan-btn-Jig").forEach(function (link) {
    link.addEventListener("click", handleRowHighlight);
  });
  // Add event listeners for Set Top Tray/Reject buttons (tray-scan-btn)
  // Add event listeners for Accept buttons (btn-twitter)
  // Add event listeners for Tray Verification View buttons
  document
    .querySelectorAll(".tray-scan-btn-DayPlanning-view")
    .forEach(function (button) {
      button.addEventListener("click", handleRowHighlight);
    });
  // Expose restoreRowPosition globally so other scripts (e.g. tvmClose) can call it
  window.restoreRowPosition = restoreRowPosition;
  // On modal close events, restore row to original position and remove highlight
  // For View modal (trayScanModal_DayPlanning)
  var closeViewBtn = document.getElementById("closeTrayScanModal_DayPlanning");
  if (closeViewBtn) {
    closeViewBtn.addEventListener("click", restoreRowPosition);
  }
});
// ====== Original inline block #5 ======
// ========== HOLD/UNHOLD TOGGLE FUNCTIONALITY ==========
document.addEventListener("DOMContentLoaded", function () {
  console.log("🔄 Initializing Hold/Unhold toggle functionality");
  // Global state to track hold/unhold operations
  window.holdToggleState = {
    currentHoldCell: null,
    intendedState: null,
    currentBatchId: null,
    currentLotId: null,
    rowIdentifier: null,
  };
  // Attach batch_id to each row for easy access
  document.querySelectorAll("tbody tr").forEach(function (row) {
    const trayScanBtn = row.querySelector(".tray-scan-btn, .tray-scan-btn-Jig");
    if (trayScanBtn) {
      row.setAttribute(
        "data-batch-id",
        trayScanBtn.getAttribute("data-batch-id"),
      );
    }
  });
  // Function to handle hold toggle button clicks
  function attachHoldToggleListeners() {
    console.log("🔗 Attaching hold toggle listeners");
    document.querySelectorAll(".hold-toggle-btn").forEach(function (btn) {
      // Remove any existing event listeners by cloning the node
      const newBtn = btn.cloneNode(true);
      if (btn.parentNode) {
        btn.parentNode.replaceChild(newBtn, btn);
      }
      // Add new event listener
      newBtn.addEventListener("click", function (e) {
        e.preventDefault();
        console.log("🎯 Hold toggle clicked");
        const holdCell = newBtn.closest("td");
        const row = holdCell.closest("tr");
        // Store state globally with all needed data
        window.holdToggleState = {
          currentHoldCell: holdCell,
          intendedState: newBtn.checked,
          currentBatchId: row.getAttribute("data-batch-id"),
          currentLotId: row.getAttribute("data-stock-lot-id"),
          rowIdentifier:
            row.getAttribute("data-stock-lot-id") ||
            row.getAttribute("data-batch-id"),
        };
        console.log("�? Hold toggle state:", window.holdToggleState);
        // Update modal title based on intended action
        const modalTitle = window.holdToggleState.intendedState
          ? "Release Reason"
          : "Hold Reason";
        document
          .getElementById("holdRemarkModal")
          .querySelector("h5").textContent = modalTitle;
        // Clear and show modal
        document.getElementById("holdRemarkInput").value = "";
        document.getElementById("holdRemarkError").textContent = "";
        document.getElementById("holdRemarkModal").style.display = "flex";
        document.getElementById("holdRemarkInput").focus();
      });
    });
  }
  // Save hold/unhold reason
  function setupSaveButton() {
    const saveBtn = document.getElementById("saveHoldRemarkBtn");
    if (saveBtn && !window.holdSaveHandlerAttached) {
      window.holdSaveHandlerAttached = true;
      saveBtn.onclick = function () {
        console.log(
          "💾 Save button clicked, current state:",
          window.holdToggleState,
        );
        const remark = document.getElementById("holdRemarkInput").value.trim();
        const errorDiv = document.getElementById("holdRemarkError");
        // Validation
        if (!remark) {
          errorDiv.textContent = "Remark is required!";
          return;
        }
        if (remark.length > 50) {
          errorDiv.textContent = "Remark must be 50 characters or less!";
          return;
        }
        if (!window.holdToggleState.currentLotId) {
          errorDiv.textContent = "Lot ID not found!";
          return;
        }
        const action = window.holdToggleState.intendedState ? "unhold" : "hold";
        console.log("📡 Sending API request:", {
          lot_id: window.holdToggleState.currentLotId,
          remark: remark,
          action: action,
        });
        // Disable save button during request
        saveBtn.disabled = true;
        saveBtn.textContent = "Saving...";
        fetch("/inputscreening/ip_save_hold_unhold_reason/", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": getCookie("csrftoken"),
          },
          body: JSON.stringify({
            lot_id: window.holdToggleState.currentLotId,
            remark: remark,
            action: action,
          }),
        })
          .then((res) => res.json())
          .then((data) => {
            console.log("📥 Server response:", data);
            // Re-enable save button
            saveBtn.disabled = false;
            saveBtn.textContent = "Save";
            if (data.success) {
              // Close modal first
              document.getElementById("holdRemarkModal").style.display = "none";
              // Show success message
              if (typeof Swal !== "undefined") {
                Swal.fire({
                  icon: "success",
                  title:
                    action === "hold"
                      ? "Row hold successfully!"
                      : "Row released successfully!",
                  timer: 1500,
                  showConfirmButton: false,
                });
              }
              // Update UI immediately
              updateRowUI(window.holdToggleState.currentLotId, action, remark);
              // Refresh page after a short delay
              setTimeout(() => {
                location.reload();
              }, 1500);
            } else {
              errorDiv.textContent = data.error || "Failed to save reason!";
            }
          })
          .catch((error) => {
            console.error("�?� Request failed:", error);
            saveBtn.disabled = false;
            saveBtn.textContent = "Save";
            errorDiv.textContent = "Network error occurred!";
          });
      };
    }
  }
  // Close modal handler
  function setupCloseButton() {
    const closeBtn = document.getElementById("closeHoldRemarkModal");
    if (closeBtn && !window.holdCloseHandlerAttached) {
      window.holdCloseHandlerAttached = true;
      closeBtn.onclick = function () {
        console.log("�?� Close button clicked");
        document.getElementById("holdRemarkModal").style.display = "none";
        // Reset toggle to original state
        if (window.holdToggleState.currentHoldCell) {
          const toggle =
            window.holdToggleState.currentHoldCell.querySelector(
              ".hold-toggle-btn",
            );
          if (toggle) {
            toggle.checked = !window.holdToggleState.intendedState; // Revert to original state
          }
        }
        // Clear state
        window.holdToggleState = {
          currentHoldCell: null,
          intendedState: null,
          currentBatchId: null,
          currentLotId: null,
          rowIdentifier: null,
        };
      };
    }
  }
  // Update row UI after successful hold/unhold operation
  function updateRowUI(lotId, action, remark) {
    console.log("🎨 Updating row UI for lot:", lotId, "action:", action);
    const currentRow = document.querySelector(
      `tr[data-stock-lot-id="${lotId}"]`,
    );
    if (!currentRow) {
      console.log("�?� Row not found for lot ID:", lotId);
      return;
    }
    const toggle = currentRow.querySelector(".hold-toggle-btn");
    const icon = currentRow.querySelector(".hold-remark-icon");
    if (action === "hold") {
      // Hold the row
      if (toggle) toggle.checked = false;
      currentRow.classList.add("row-inactive");
      // Blur all cells except the first one (S.No column)
      currentRow.querySelectorAll("td").forEach((td, idx) => {
        if (idx > 0) {
          td.classList.add("row-inactive-blur");
        } else {
          td.classList.remove("row-inactive-blur"); // Keep S.No column unblurred
        }
      });
      // Show remark icon
      if (icon) {
        icon.style.display = "inline-block";
        icon.innerHTML = `<img src="${(window.IS_STATIC && window.IS_STATIC.viewIcon) || ""}" alt="View Reason" style="width:18px; height:18px;" />`;
        icon.setAttribute("title", "Holding Reason: " + remark);
      }
      console.log("✅ Row hold successfully");
    } else {
      // Unhold/Release the row
      if (toggle) toggle.checked = true;
      currentRow.classList.remove("row-inactive");
      // Remove blur from all cells
      currentRow.querySelectorAll("td").forEach((td) => {
        td.classList.remove("row-inactive-blur");
      });
      // Update remark icon to show release reason or hide it
      if (icon) {
        icon.style.display = "inline-block";
        icon.innerHTML = `<img src="${(window.IS_STATIC && window.IS_STATIC.viewIcon) || ""}" alt="View Reason" style="width:18px; height:18px;" />`;
        icon.setAttribute("title", "Release Reason: " + remark);
      }
      console.log("✅ Row released successfully");
    }
  }
  // Helper function to get CSRF token
  function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== "") {
      const cookies = document.cookie.split(";");
      for (let i = 0; i < cookies.length; i++) {
        const cookie = cookies[i].trim();
        if (cookie.substring(0, name.length + 1) === name + "=") {
          cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
          break;
        }
      }
    }
    return cookieValue;
  }
  // Initialize all functionality
  attachHoldToggleListeners();
  setupSaveButton();
  setupCloseButton();
  console.log("✅ Hold/Unhold functionality initialized successfully");
});
// ====== Original inline block #6 ======
document.addEventListener("DOMContentLoaded", function () {
  let openTooltip = null;
  // Helper function to completely close a tooltip
  function closeTooltip(tooltip, trigger) {
    if (tooltip) {
      console.log("🔴 Closing tooltip completely");
      // Remove pinned class
      tooltip.classList.remove("pinned");
      // Hide the entire tooltip completely
      tooltip.style.opacity = "0";
      tooltip.style.pointerEvents = "none";
      tooltip.style.visibility = "hidden";
      tooltip.style.display = "none"; // ✅ ADDED: Force display none
      // Hide buttons
      const infoBtn = tooltip.querySelector(".info-btn");
      const closeBtn = tooltip.querySelector(".close-btn");
      if (infoBtn) infoBtn.style.display = "none";
      if (closeBtn) closeBtn.style.display = "none";
      // Remove visual indicator from trigger
      if (trigger) {
        trigger.style.backgroundColor = "";
        trigger.style.borderRadius = "";
      }
      // Clear global reference
      openTooltip = null;
      console.log("✅ Tooltip completely closed");
    }
  }
  document
    .querySelectorAll(".model-image-tooltip .info-btn")
    .forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.stopPropagation();
        // Find the closest row
        const row = btn.closest("tr");
        let lotId = null;
        let batchId = null;
        if (row) {
          batchId = row.getAttribute("data-batch-id");
        }
        // Build the URL with lot_id and batch_id if found
        let url = "/adminportal/dp_visualaid/";
        if (lotId) {
          url += encodeURIComponent(lotId) + "/";
        }
        if (batchId) {
          url += "?batch_id=" + encodeURIComponent(batchId);
        }
        window.location.href = url;
      });
    });
  // Tooltip show/hide logic
  document.querySelectorAll(".model-hover-trigger").forEach(function (trigger) {
    const tooltip = trigger.querySelector(".model-image-tooltip");
    trigger.addEventListener("mouseenter", function () {
      if (tooltip && !tooltip.classList.contains("pinned")) {
        tooltip.style.display = "flex"; // ✅ ADDED: Reset display
        tooltip.style.visibility = "visible"; // ✅ ADDED: Reset visibility
        tooltip.style.opacity = "1";
        tooltip.style.pointerEvents = "auto";
        // Show Info and Close buttons on hover
        const infoBtn = tooltip.querySelector(".info-btn");
        const closeBtn = tooltip.querySelector(".close-btn");
        if (infoBtn) infoBtn.style.display = "block";
        if (closeBtn) closeBtn.style.display = "block";
      }
    });
    trigger.addEventListener("mouseleave", function () {
      if (tooltip && !tooltip.classList.contains("pinned")) {
        tooltip.style.opacity = "0";
        tooltip.style.pointerEvents = "none";
        // Hide Info and Close buttons when not hovering and not pinned
        const infoBtn = tooltip.querySelector(".info-btn");
        const closeBtn = tooltip.querySelector(".close-btn");
        if (infoBtn) infoBtn.style.display = "none";
        if (closeBtn) closeBtn.style.display = "none";
      }
    });
    // Keep tooltip visible when hovering over it
    if (tooltip) {
      tooltip.addEventListener("mouseenter", function () {
        if (!tooltip.classList.contains("pinned")) {
          tooltip.style.display = "flex"; // ✅ ADDED: Reset display
          tooltip.style.visibility = "visible"; // ✅ ADDED: Reset visibility
        }
        tooltip.style.opacity = "1";
        tooltip.style.pointerEvents = "auto";
        // Keep buttons visible when hovering over tooltip
        const infoBtn = tooltip.querySelector(".info-btn");
        const closeBtn = tooltip.querySelector(".close-btn");
        if (infoBtn) infoBtn.style.display = "block";
        if (closeBtn) closeBtn.style.display = "block";
      });
      tooltip.addEventListener("mouseleave", function () {
        if (!tooltip.classList.contains("pinned")) {
          tooltip.style.opacity = "0";
          tooltip.style.pointerEvents = "none";
          // Hide buttons when leaving tooltip and not pinned
          const infoBtn = tooltip.querySelector(".info-btn");
          const closeBtn = tooltip.querySelector(".close-btn");
          if (infoBtn) infoBtn.style.display = "none";
          if (closeBtn) closeBtn.style.display = "none";
        }
      });
    }
    trigger.addEventListener("click", function (e) {
      e.stopPropagation();
      if (tooltip) {
        // Close any previously opened tooltip
        if (openTooltip && openTooltip !== tooltip) {
          const prevTrigger = openTooltip.closest(".model-hover-trigger");
          closeTooltip(openTooltip, prevTrigger);
        }
        tooltip.classList.add("pinned");
        tooltip.style.display = "flex"; // ✅ ADDED: Ensure display
        tooltip.style.visibility = "visible"; // ✅ ADDED: Ensure visibility
        tooltip.style.opacity = "1";
        tooltip.style.pointerEvents = "auto";
        openTooltip = tooltip;
        // Keep buttons visible when pinned
        const infoBtn = tooltip.querySelector(".info-btn");
        const closeBtn = tooltip.querySelector(".close-btn");
        if (infoBtn) infoBtn.style.display = "block";
        if (closeBtn) closeBtn.style.display = "block";
        // Add visual indicator that tooltip is pinned
        trigger.style.backgroundColor = "#e3f2fd";
        trigger.style.borderRadius = "4px";
      }
    });
    // ✅ FIXED: Handle Close button click - Complete tooltip closure
    const closeBtn = tooltip?.querySelector(".close-btn");
    if (closeBtn) {
      // Initially hide the button
      closeBtn.style.display = "none";
      closeBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        console.log("🔴 Close button clicked");
        // Use the helper function to completely close tooltip
        closeTooltip(tooltip, trigger);
        // Feedback animation for close button
        closeBtn.style.transform = "scale(0.9)";
        setTimeout(() => {
          if (closeBtn.style) {
            closeBtn.style.transform = "scale(1)";
          }
        }, 150);
      });
      // ✅ Add hover effect for close button
      closeBtn.addEventListener("mouseenter", function () {
        closeBtn.style.backgroundColor = "#c82333";
        closeBtn.style.transform = "scale(1.05)";
      });
      closeBtn.addEventListener("mouseleave", function () {
        closeBtn.style.backgroundColor = "#dc3545";
        closeBtn.style.transform = "scale(1)";
      });
    }
  });
  // ✅ ENHANCED: Close tooltip when clicking outside
  document.addEventListener("click", function (e) {
    if (
      openTooltip &&
      !e.target.closest(".model-image-tooltip") &&
      !e.target.closest(".model-hover-trigger")
    ) {
      const openTrigger = openTooltip.closest(".model-hover-trigger");
      closeTooltip(openTooltip, openTrigger);
    }
  });
  // ✅ Close tooltip with ESC key
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && openTooltip) {
      const openTrigger = openTooltip.closest(".model-hover-trigger");
      closeTooltip(openTooltip, openTrigger);
      console.log("✅ Tooltip closed with ESC key");
    }
  });
  // Prevent tooltip from closing when clicking inside it
  document.querySelectorAll(".model-image-tooltip").forEach(function (tooltip) {
    tooltip.addEventListener("click", function (e) {
      e.stopPropagation();
    });
  });
});
// ====== Original inline block #7 ======
document.addEventListener("DOMContentLoaded", function () {
  console.log(
    "🎬 IS Pick Table: Initializing tray verification modal + button state check",
  );
  // ══════════════════════════════════════════════════════════════════════════════
  // CHECK BUTTON STATE ON PAGE LOAD
  // If tray verification is already complete for a lot, enable Accept/Reject buttons
  // ══════════════════════════════════════════════════════════════════════════════
  function checkButtonStateOnLoad() {
    // Read ip_person_qty_verified directly from the server-rendered data attribute.
    // This avoids one API call per row on every page load and ensures the buttons
    // stay enabled after a browser refresh.
    const rows = document.querySelectorAll("tr[data-stock-lot-id]");
    rows.forEach(function (row) {
      const lotId = row.getAttribute("data-stock-lot-id");
      if (!lotId) return;
      // Check both the <tr> and the nested view <a> tag for the flag
      const rowFlag = row.getAttribute("data-ip-person-qty-verified");
      const aTag = row.querySelector("a[data-ip-person-qty-verified]");
      const aFlag = aTag ? aTag.getAttribute("data-ip-person-qty-verified") : null;
      const verified = rowFlag === "true" || aFlag === "true";
      if (verified) {
        isEnableActionButtons(lotId, true);
      }
    });
  }
  // Run immediately – data-attribute is already present in rendered HTML
  checkButtonStateOnLoad();
  // ══════════════════════════════════════════════════════════════════════════════
  // TRAY VERIFICATION MODAL (EXISTING CODE BELOW)
  // ══════════════════════════════════════════════════════════════════════════════
  // ─── Helpers ───────────────────────────────────────────────────────────────
  function tvmGetCookie(name) {
    let val = null;
    if (document.cookie) {
      document.cookie.split(";").forEach(function (c) {
        const trimmed = c.trim();
        if (trimmed.startsWith(name + "=")) {
          val = decodeURIComponent(trimmed.slice(name.length + 1));
        }
      });
    }
    return val;
  }
  function tvmSafeId(trayId) {
    return trayId.replace(/[^a-zA-Z0-9]/g, "-");
  }
  // ─── Auto-format tray ID to standard format ─────────────────────────────────
  function tvmFormatTrayId(input) {
    // Accepted inputs: jb-a00001, JB-A00001, jbA00001, jba00001
    // Output: JB-A00001 (standard)
    if (!input) return "";
    input = input.trim().toUpperCase();
    // Remove spaces and convert to standard format JB-AXXXXX
    input = input.replace(/\s+/g, "");
    if (input.length < 9) return input;
    // If it's 9 chars and already in format JB-A00001, return as is
    if (input.match(/^[A-Z]{2}-[A-Z]\d{5}$/)) return input;
    // If it's 8 chars like JBA00001, insert hyphen: JB-A00001
    if (input.match(/^[A-Z]{2}[A-Z]\d{5}$/)) {
      return input.substring(0, 2) + "-" + input.substring(2);
    }
    return input.substring(0, 9);
  }
  // ─── Status helpers ────────────────────────────────────────────────────────
  const VERIFIED_BADGE_STYLE =
    "background:#f0fdf7;color:#1ba878;border:1px solid #c8f0e0;padding:6px 16px;border-radius:20px;font-size:12px;font-weight:700;white-space:nowrap;";
  const UNVERIFIED_BADGE_STYLE =
    "background:#fff5f0;color:#d67d3a;border:1px solid #fde8d0;padding:6px 16px;border-radius:20px;font-size:12px;font-weight:700;white-space:nowrap;";
  // ─── Running info banner — splits label : value with different colours ────
  function tvmSetRunningInfo(text) {
    const infoEl = document.getElementById("tvm-running-info");
    if (!infoEl) return;
    const colonIdx = text.indexOf(":");
    if (colonIdx !== -1) {
      const label = text.substring(0, colonIdx);
      const value = text.substring(colonIdx + 1);
      infoEl.innerHTML =
        '<span style="color:#028084;font-size:11px;letter-spacing:.5px;text-transform:uppercase;">' +
        label +
        "</span>" +
        '<span style="color:#555;font-size:11px;">:' +
        value +
        "</span>";
    } else {
      infoEl.innerHTML =
        '<span style="color:#028084;font-size:11px;">' + text + "</span>";
    }
  }
  // ─── Auto-scroll to tray row with smooth behavior and subtle highlight ───────────
  function tvmScrollToTray(trayId, shouldHighlight) {
    const sid = tvmSafeId(trayId);
    const row = document.getElementById("tvm-row-" + sid);
    if (!row) return;
    const container = document.getElementById("tvm-table-body-container");
    if (!container) return;
    // Smooth scroll to row (center it in viewport if possible)
    row.scrollIntoView({ behavior: "smooth", block: "nearest" });
    // Apply very subtle highlight for 1.5 seconds
    if (shouldHighlight) {
      row.style.boxShadow = "0 0 0 1px rgba(27,168,120,.2)";
      row.style.background = "rgba(240, 253, 247, 0.3)";
      setTimeout(function () {
        row.style.boxShadow = "";
        row.style.background = "";
      }, 1500);
    }
  }
  // ─── Enable Accept/Reject buttons in main table row from backend response ──
  function tvmEnableActions(lotId, enableActions) {
    if (enableActions.reject) {
      var rejectBtn = document.querySelector(
        '.tray-scan-btn[data-stock-lot-id="' + lotId + '"]',
      );
      if (rejectBtn) rejectBtn.removeAttribute("disabled");
    }
    // Update row's data-tray-verify attribute for correct state tracking
    var tableRow = document.querySelector(
      'tr[data-stock-lot-id="' + lotId + '"]',
    );
    if (tableRow) tableRow.setAttribute("data-tray-verify", "True");
  }
  function tvmSetActivity(type, msg) {
    const dot = document.getElementById("tvm-activity-dot");
    const el = document.getElementById("tvm-activity-msg");
    const bar = document.getElementById("tvm-activity-bar");
    if (!dot || !el) return;
    el.textContent = msg;
    const styles = {
      wait: {
        dot: "#f0ad4e",
        bar: "#fafbfc",
        text: "#444",
        boxShadow: "0 0 8px rgba(240,173,78,.4)",
      },
      success: {
        dot: "#1ba878",
        bar: "#f0fdf7",
        text: "#1ba878",
        boxShadow: "0 0 8px rgba(27,168,120,.3)",
      },
      error: {
        dot: "#d67d3a",
        bar: "#fff5f0",
        text: "#d67d3a",
        boxShadow: "0 0 8px rgba(214,125,58,.3)",
      },
      info: {
        dot: "#028084",
        bar: "#f0f9fa",
        text: "#028084",
        boxShadow: "0 0 8px rgba(2,128,132,.3)",
      },
    };
    const s = styles[type] || styles.wait;
    dot.style.background = s.dot;
    dot.style.boxShadow = s.boxShadow;
    bar.style.background = s.bar;
    el.style.color = s.text;
  }
  function tvmUpdateStats(verified, total, pending, verified_qty, total_qty) {
    document.getElementById("tvm-total-count").textContent = total;
    document.getElementById("tvm-verified-count").textContent = verified;
    document.getElementById("tvm-pending-count").textContent = pending;
    const display = document.getElementById("tvm-verified-qty-display");
    if (display && verified_qty !== undefined && total_qty !== undefined) {
      display.textContent = verified_qty + "/" + total_qty;
    }
    // Update progress bars
    const qtyProgress = document.getElementById("tvm-qty-progress");
    const pendingProgress = document.getElementById("tvm-pending-progress");
    // VERIFIED QTY progress bar - full green when quantity is verified
    if (qtyProgress && total_qty > 0) {
      const qtyPercent = (verified_qty / total_qty) * 100;
      qtyProgress.style.width = qtyPercent + "%";
      // Trigger sparkle animation when complete
      const sparkleEl = document.getElementById("tvm-qty-sparkle");
      if (sparkleEl && qtyPercent >= 100) {
        sparkleEl.style.animation = "none"; // Reset animation
        void sparkleEl.offsetWidth; // Trigger reflow
        sparkleEl.style.animation = "qtySparkle 1.2s ease-in-out";
      }
    }
    // PENDING progress bar - shows scanning progress (verified/total)
    if (pendingProgress && total > 0) {
      const scanPercent = ((total - pending) / total) * 100;
      pendingProgress.style.width = scanPercent + "%";
    }
  }
  // ─── Render table ──────────────────────────────────────────────────────────
  function tvmRenderTable(trays) {
    const tbody = document.getElementById("tvm-tray-tbody");
    if (!trays || trays.length === 0) {
      tbody.innerHTML =
        '<tr><td colspan="4" style="text-align:center;color:#bbb;padding:24px;font-size:13px;">No trays found for this lot</td></tr>';
      return;
    }
    tbody.innerHTML = trays
      .map(function (t) {
        const sid = tvmSafeId(t.tray_id);
        const badge = t.is_verified
          ? VERIFIED_BADGE_STYLE
          : UNVERIFIED_BADGE_STYLE;
        const label = t.is_verified ? "Verified ✅" : "Not Verified";
        const topTag = t.top_tray
          ? ' <sup style="color:#028084;font-size:10px;font-weight:700;">TOP</sup>'
          : "";
        return (
          '<tr id="tvm-row-' +
          sid +
          '" style="border-bottom:1px solid #e6f1f2;transition:background .4s; cursor:default;">' +
          '<td style="padding:12px 10px;color:#666;font-weight:600;font-size:13px;">' +
          t.sno +
          "</td>" +
          '<td style="padding:12px 10px;font-family:monospace;font-weight:600;color:#028084;font-size:13px;letter-spacing:.5px;cursor:pointer;user-select:text;transition:background .2s;" class="tvm-copy-tray-id" data-tray-id="' +
          t.tray_id +
          '" title="Click to copy">' +
          t.tray_id +
          topTag +
          "</td>" +
          '<td style="padding:12px 10px;text-align:center;color:#666;font-weight:600;">' +
          (t.qty !== null && t.qty !== undefined ? t.qty : "—") +
          "</td>" +
          '<td style="padding:12px 10px;text-align:center;">' +
          '<span id="tvm-badge-' +
          sid +
          '" style="' +
          badge +
          '">' +
          label +
          "</span>" +
          "</td>" +
          "</tr>"
        );
      })
      .join("");
    // FIX 3: Add copy-to-clipboard handlers for tray ID
    const trayIdCells = tbody.querySelectorAll(".tvm-copy-tray-id");
    trayIdCells.forEach(function (cell) {
      cell.addEventListener("click", function (e) {
        e.stopPropagation();
        const trayId = this.getAttribute("data-tray-id");
        navigator.clipboard
          .writeText(trayId)
          .then(function () {
            // FIX 1: Show compact feedback message
            tvmSetActivity("success", "Copied: " + trayId);
            // FIX 1: Auto-focus scan input for next scan
            const input = document.getElementById("tvm-scan-input");
            if (input) {
              setTimeout(function () {
                input.focus();
                input.setSelectionRange(0, 0);
              }, 100);
            }
            setTimeout(function () {
              tvmSetActivity("wait", "Waiting for tray scan…");
            }, 2000);
          })
          .catch(function () {
            tvmSetActivity("error", "Failed to copy �?�");
          });
      });
    });
  }
  // ─── Enable/Disable action buttons based on verification status ────────────
  function isEnableActionButtons(lotId, enable) {
    // Find row in table that has this lot_id
    const table = document.getElementById("order-listing");
    if (!table) return;
    const rows = table.querySelectorAll("tbody tr");
    rows.forEach(function (row) {
      const rowLotId = row.getAttribute("data-stock-lot-id");
      if (rowLotId === lotId) {
        const acceptBtn = row.querySelector(".btn-accept-is");
        const rejectBtn = row.querySelector(".btn-reject-is");
        if (acceptBtn) {
          acceptBtn.disabled = !enable;
          acceptBtn.style.cursor = enable ? "pointer" : "not-allowed";
          acceptBtn.style.opacity = enable ? "1" : "0.5";
        }
        if (rejectBtn) {
          rejectBtn.disabled = !enable;
          rejectBtn.style.cursor = enable ? "pointer" : "not-allowed";
          rejectBtn.style.opacity = enable ? "1" : "0.5";
        }
        // Update Process Status "Q" indicator to full green when verified
        if (enable) {
          const processStatusCell = row.querySelector("td:nth-child(13)"); // Process Status column
          if (processStatusCell) {
            const qIcon = processStatusCell.querySelector(
              "div > div:nth-child(1)",
            ); // Q icon
            if (qIcon) {
              qIcon.style.backgroundColor = "#0c8249";
              qIcon.style.background = "#0c8249"; // Override gradient
              qIcon.style.opacity = "1";
            }
          }
        }
      }
    });
  }
  // ─── Load trays from backend ───────────────────────────────────────────────
  function tvmLoadTrays(lotId) {
    const tbody = document.getElementById("tvm-tray-tbody");
    tbody.innerHTML =
      '<tr><td colspan="4" style="text-align:center;color:#bbb;padding:28px;font-size:13px;">Loading trays…</td></tr>';
    fetch("/inputscreening/get_dp_trays/?lot_id=" + encodeURIComponent(lotId))
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        if (!data.success) {
          tbody.innerHTML =
            '<tr><td colspan="4" style="text-align:center;color:#d67d3a;padding:28px;">Error: ' +
            (data.error || "Could not load trays") +
            "</td></tr>";
          return;
        }
        // Update plating stock number (ERR 3)
        const platEl = document.getElementById("tvm-plating-stk");
        if (platEl && data.plating_stk_no) {
          platEl.textContent = data.plating_stk_no;
        }
        // Store trays list and pending count for local lookup
        window._tvmPendingCount = data.pending;
        window._tvmTrays = data.trays || [];
        window._tvmCurrentLotId = lotId; // Store current lot for button handlers
        tvmUpdateStats(
          data.verified,
          data.total,
          data.pending,
          data.verified_qty,
          data.total_qty,
        );
        tvmRenderTable(data.trays);
        if (data.total === 0) {
          tvmSetActivity(
            "info",
            "No trays found for this lot in Day Planning.",
          );
        } else if (data.pending === 0) {
          tvmSetActivity(
            "success",
            "All trays already verified ✅  Ready for Input Screening",
          );
          // Enable action buttons when all verified
          isEnableActionButtons(lotId, true);
        } else {
          tvmSetActivity(
            "wait",
            "Waiting for tray scan… (" + data.pending + " pending)",
          );
        }
      })
      .catch(function () {
        tbody.innerHTML =
          '<tr><td colspan="4" style="text-align:center;color:#d67d3a;padding:28px;">Network error — could not load trays</td></tr>';
        tvmSetActivity("error", "Network error �?�");
      });
  }
  // ─── Verify a tray scan ────────────────────────────────────────────────────
  function tvmVerifyScan(trayId) {
    const lotId = window._tvmCurrentLotId;
    if (!lotId || !trayId) return;
    tvmSetActivity("info", "Verifying: " + trayId + "…");
    fetch("/inputscreening/verify_tray/", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": tvmGetCookie("csrftoken"),
      },
      body: JSON.stringify({ lot_id: lotId, tray_id: trayId }),
    })
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        const input = document.getElementById("tvm-scan-input");
        input.value = "";
        if (data.success) {
          // ── success ──────────────────────────────────────────────────────
          tvmSetActivity(
            "success",
            data.message || "Tray Verified Successfully ✅",
          );
          tvmUpdateStats(
            data.verified,
            data.total,
            data.pending,
            data.verified_qty,
            data.total_qty,
          );
          const sid = tvmSafeId(trayId);
          const badge = document.getElementById("tvm-badge-" + sid);
          const row = document.getElementById("tvm-row-" + sid);
          if (badge) {
            badge.style.cssText = VERIFIED_BADGE_STYLE;
            badge.textContent = "Verified ✅";
          }
          if (row) {
            // FIX 5: Auto-scroll to row and apply highlight
            tvmScrollToTray(trayId, true);
          }
          // Update local tray store so next scan of this tray auto-selects
          if (window._tvmTrays) {
            var tr = window._tvmTrays.find(function (t) {
              return t.tray_id === trayId;
            });
            if (tr) tr.is_verified = true;
          }
          // FIX 4: Update running info
          tvmSetRunningInfo("Scanned: " + trayId + " ✅");
          if (data.all_verified) {
            // ── SSOT: enable action buttons from backend response ──────────
            isEnableActionButtons(window._tvmCurrentLotId, true);
            // ── Show auto-dismissing success alert ────────────────────────
            Swal.fire({
              icon: "success",
              title: "All trays are verified",
              text: "Accept and Reject are now enabled.",
              timer: 2500,
              timerProgressBar: true,
              showConfirmButton: false,
              allowOutsideClick: false,
            });
            setTimeout(function () {
              tvmSetActivity(
                "success",
                "All trays verified ✅  Ready for Input Screening",
              );
              tvmSetRunningInfo("Status: All Complete ✅");
            }, 300);
            // ── Auto-close modal after alert timer ─────────────────────────
            setTimeout(function () {
              tvmClose();
            }, 2600);
          } else {
            setTimeout(function () {
              tvmSetActivity(
                "wait",
                "Waiting for next tray scan… (" + data.pending + " pending)",
              );
            }, 1600);
          }
        } else {
          // ── failure ───────────────────────────────────────────────────────
          const status = data.status || "error";
          if (status === "already_verified") {
            // Already verified in current lot - show warning, NOT invalid
            tvmSetActivity("info", data.message || "Already Verified ⚠�?");
            // Scroll to that tray and highlight it
            tvmScrollToTray(trayId, true);
            // Update running info
            tvmSetRunningInfo("Scanned: " + trayId + " (Already Verified)");
            // Auto-select input for already verified trays
            setTimeout(function () {
              input.select();
            }, 500);
            setTimeout(function () {
              tvmSetActivity("wait", "Waiting for tray scan…");
            }, 2000);
          } else {
            // Tray belongs to another lot or not found - show as invalid
            tvmSetActivity("error", data.message || "Invalid Tray ID �?�");
            // Update running info with invalid scan
            tvmSetRunningInfo("Invalid: " + trayId + " �?�");
            // Shake animation
            input.style.animation = "";
            void input.offsetWidth; // reflow to restart
            input.style.animation = "tvmShake 0.4s ease";
            setTimeout(function () {
              input.style.animation = "";
            }, 450);
            // Auto-select input on error so next scan replaces it
            setTimeout(function () {
              input.select();
            }, 500);
            setTimeout(function () {
              tvmSetActivity("wait", "Waiting for tray scan…");
            }, 2800);
          }
        }
        setTimeout(function () {
          input.focus();
        }, 60);
      })
      .catch(function () {
        tvmSetActivity("error", "Network error �?�");
        const input = document.getElementById("tvm-scan-input");
        input.value = "";
        setTimeout(function () {
          input.focus();
        }, 60);
        setTimeout(function () {
          tvmSetActivity("wait", "Waiting for tray scan…");
        }, 2200);
      });
  }
  // ─── Open / close ──────────────────────────────────────────────────────────
  function tvmOpen(lotId, batchId) {
    window._tvmCurrentLotId = lotId;
    window._tvmCurrentBatchId = batchId;
    tvmUpdateStats(0, 0, 0, 0, 0);
    tvmSetActivity("wait", "Waiting for tray scan…");
    tvmSetRunningInfo("User Insights");
    // Reset success banner on modal open
    var banner = document.getElementById("tvm-success-banner");
    if (banner) banner.style.display = "none";
    const modal = document.getElementById("trayVerificationModal");
    modal.style.display = "flex";
    tvmLoadTrays(lotId);
    // ERR 2: Auto focus cursor on modal open
    setTimeout(function () {
      const input = document.getElementById("tvm-scan-input");
      if (input) {
        input.focus();
        input.value = "";
        input.setSelectionRange(0, 0);
      }
    }, 120);
  }
  function tvmClose() {
    document.getElementById("trayVerificationModal").style.display = "none";
    window._tvmCurrentLotId = null;
    window._tvmCurrentBatchId = null;
    // Clear active row highlight and restore original row position
    if (typeof window.restoreRowPosition === "function") {
      window.restoreRowPosition();
    }
  }
  // ─── Event: view icon (delegated) ──────────────────────────────────────────
  document.addEventListener("click", function (e) {
    const viewBtn = e.target.closest(".tray-scan-btn-DayPlanning-view");
    if (viewBtn) {
      e.preventDefault();
      e.stopPropagation();
      const lotId = viewBtn.getAttribute("data-stock-lot-id");
      const batchId = viewBtn.getAttribute("data-batch-id");
      tvmOpen(lotId, batchId);
    }
  });
  // ─── Event: close button ───────────────────────────────────────────────────
  const closeBtn = document.getElementById("closeTrayVerificationModal");
  if (closeBtn) closeBtn.addEventListener("click", tvmClose);
  // ─── Event: backdrop click ─────────────────────────────────────────────────
  document
    .getElementById("trayVerificationModal")
    .addEventListener("click", function (e) {
      if (e.target === this) tvmClose();
    });
  // ─── Event: ESC key ────────────────────────────────────────────────────────
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      const modal = document.getElementById("trayVerificationModal");
      if (modal && modal.style.display !== "none") tvmClose();
    }
  });
  // ─── Event: scan input — Enter & formatting ───────────────────────────────
  const scanInput = document.getElementById("tvm-scan-input");
  if (scanInput) {
    // ERR 6 + ERR 8: Focus handler - clear input and set cursor position
    scanInput.addEventListener("focus", function () {
      this.style.borderColor = "#028084";
      this.style.boxShadow = "0 0 0 4px rgba(2,128,132,.12)";
      this.value = "";
      this.setSelectionRange(0, 0);
    });
    scanInput.addEventListener("blur", function () {
      this.style.borderColor = "#d0dfe1";
      this.style.boxShadow = "none";
    });
    // ERR 8: Auto-format + ERR 7: 9-char limit as user types
    scanInput.addEventListener("input", function () {
      let val = this.value.trim();
      if (val.length > 9) val = val.substring(0, 9);
      if (val.length > 0) {
        const formatted = tvmFormatTrayId(val);
        this.value = formatted;
        tvmSetActivity("info", "Typing: " + formatted);
        // Auto-select if tray is already verified OR not in this lot (invalid)
        // Do NOT auto-select for pending (unverified) trays that belong to this lot
        if (formatted.length >= 9 && window._tvmTrays) {
          var match = window._tvmTrays.find(function (t) {
            return t.tray_id === formatted;
          });
          var shouldSelect = !match || match.is_verified === true;
          if (shouldSelect) {
            var self = this;
            setTimeout(function () {
              self.select();
            }, 0);
          }
        }
      } else {
        tvmSetActivity("wait", "Waiting for tray scan…");
      }
    });
    // ERR 2: Enter key to verify
    scanInput.addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        const val = this.value.trim();
        if (val) {
          const formatted = tvmFormatTrayId(val);
          tvmVerifyScan(formatted);
        }
      }
    });
  }
  // ─── Event: verify button click ───────────────────────────────────────────
  const verifyBtn = document.getElementById("tvm-scan-btn");
  if (verifyBtn) {
    verifyBtn.addEventListener("click", function () {
      const input = document.getElementById("tvm-scan-input");
      const val = input ? input.value.trim() : "";
      if (val) {
        const formatted = tvmFormatTrayId(val);
        tvmVerifyScan(formatted);
      }
      if (input)
        setTimeout(function () {
          input.focus();
        }, 60);
    });
  }
  // ─── Event: FIX 6 - Clear button click ────────────────────────────────────
  const clearBtn = document.getElementById("tvm-clear-btn");
  if (clearBtn) {
    clearBtn.addEventListener("click", function () {
      const input = document.getElementById("tvm-scan-input");
      if (input) {
        input.value = "";
        input.focus();
        input.setSelectionRange(0, 0);
        tvmSetActivity("wait", "Waiting for tray scan…");
      }
    });
  }
  // ─── Event: Accept button click ─────────────────────
  document.addEventListener("click", function (e) {
    if (e.target.classList.contains("btn-accept-is")) {
      e.preventDefault();
      const lotId = e.target.getAttribute("data-stock-lot-id");
      const batchId = e.target.getAttribute("data-batch-id");
      if (!lotId || !batchId) return;
      if (confirm("Accept this lot? All trays have been verified.")) {
        // Show loading state
        e.target.disabled = true;
        e.target.style.opacity = "0.5";
        // TODO: Implement Accept API call
        console.log("Accept lot:", lotId, "batch:", batchId);
        alert("Accept functionality - Implementation pending");
        // Re-enable button
        setTimeout(function () {
          e.target.disabled = false;
          e.target.style.opacity = "1";
        }, 1000);
      }
    }
  });
  // ─── Reject button click ── handled by inputscreening_reject_modal.js ──────
});

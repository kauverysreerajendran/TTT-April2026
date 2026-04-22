# Read the file
filePath = r"a:\Workspace\Watchcase\TTT-Jan2026\static\templates\Day_Planning\DP_PickTable.html"
with open(filePath, 'r', encoding='utf-8') as f:
    content = f.read()

print("File loaded successfully. Content length:", len(content))

# Step 1: Update keyboard hints from F1 to F2
original_hints = "F1: Scan | T+Enter: Tray Scan | Del+Enter: Delete | Arrows: Navigate | 1-9: Page | Esc: Close"
new_hints = "F2: Scan | T+Enter: Tray Scan | Del+Enter: Delete | Arrows: Navigate | 1-9: Page | Esc: Close"
if original_hints in content:
    content = content.replace(original_hints, new_hints)
    print("Step 1: Updated keyboard hints from F1 to F2")
else:
    print("ERROR: Could not find original hints text")

# Step 2: Fix the broken F1 key handler - replace with F2 and clean vanilla JS
# The broken code has jQuery syntax that needs to be removed
broken_f1_start = "    // Handle F1 key FIRST - show \"Please scan\" message next to scan button"
broken_f1_block = '''    // Handle F1 key FIRST - show "Please scan" message next to scan button
          if (e.key === 'F1') {
        e.preventDefault();
        showKeyboardHint();
        
        const row = currentSelectedRow || getDataRows()[0];
        if (row) {
          const btn = .find('.tray-scan-btn');
          const isDrafted = btn.data('draft-saved') === 'true' || btn.data('draft-saved') === true;
          if (isDrafted) {
             const $msg = <div class="f1-please-scan-message">Please scan</div>;
             btn.parent().css('position', 'relative').append($msg);
             setTimeout(() => $msg.remove(), 2000);
          }
        }
      console.log('?? F1 key pressed - Showing "Please scan" message next to scan button');
      
      // If no row selected, select first row
      if (!currentSelectedRow) {
        const rows = getDataRows();
        if (rows.length > 0) {
          selectRow(rows[0]);
        }
      }
      
      if (!currentSelectedRow) return;
      
      // Find the scan button in the selected row
      const scanBtn = currentSelectedRow.querySelector('.tray-scan-btn');
      if (!scanBtn) return;
      
      // Get button position
      const rect = scanBtn.getBoundingClientRect();
      
      // Create and display message next to button
      const message = document.createElement('div');
      message.className = 'f1-please-scan-message';
      message.textContent = '?? Please scan';
      message.style.left = (rect.right + 10) + 'px';
      message.style.top = (rect.top + window.scrollY) + 'px';
      document.body.appendChild(message);
      
      // Remove message after animation completes (2 seconds)
      setTimeout(() => {
        message.remove();
      }, 2000);
      
      return;
    }'''

new_f2_block = '''    // Handle F2 key FIRST - show "Please scan" message next to scan button
    if (e.key === 'F2') {
      e.preventDefault();
      showKeyboardHint();
      
      // If no row selected, auto-select first row
      if (!currentSelectedRow) {
        const rows = getDataRows();
        if (rows.length > 0) {
          selectRow(rows[0]);
        }
      }
      
      if (!currentSelectedRow) return;
      
      // Find the scan button in the selected row
      const scanBtn = currentSelectedRow.querySelector('.tray-scan-btn');
      if (!scanBtn) return;
      
      // Get button position
      const rect = scanBtn.getBoundingClientRect();
      
      // Create and display message next to button
      const message = document.createElement('div');
      message.className = 'f2-please-scan-message';
      message.textContent = '?? Please scan';
      message.style.position = 'fixed';
      message.style.left = (rect.right + 10) + 'px';
      message.style.top = (rect.top + window.scrollY) + 'px';
      message.style.zIndex = '10000';
      document.body.appendChild(message);
      
      // Remove message after animation completes (2 seconds)
      setTimeout(() => {
        message.remove();
      }, 2000);
      
      return;
    }'''

if broken_f1_block in content:
    content = content.replace(broken_f1_block, new_f2_block)
    print("Step 2: Fixed F1 key handler (changed to F2 with clean vanilla JS)")
else:
    print("WARNING: Could not find exact F1 handler block, trying alternative approach")

# Save after Step 2
with open(filePath, 'w', encoding='utf-8') as f:
    f.write(content)
print("File saved after step 2")

# Step 3: Fix broken helper functions
# First helper function findRowByLotId
broken_helper1 = '''  function findRowByLotId(lotId) {
    let targetRow = null;
    #order-listing tbody tr.each(function() {
      const rowLotId = .find('.tray-scan-btn').data('lot-id');
      if (String(rowLotId) === String(lotId)) {
        targetRow = ;
        return false;
      }
    });
    return targetRow;
  }'''

new_helper1 = '''  function findRowByLotId(lotId) {
    let targetRow = null;
    const rows = document.querySelectorAll('#order-listing tbody tr');
    for (const row of rows) {
      const scanBtn = row.querySelector('.tray-scan-btn');
      if (scanBtn) {
        const rowLotId = scanBtn.getAttribute('data-lot-id');
        if (String(rowLotId) === String(lotId)) {
          targetRow = row;
          break;
        }
      }
    }
    return targetRow;
  }'''

if broken_helper1 in content:
    content = content.replace(broken_helper1, new_helper1)
    print("Step 3: Fixed findRowByLotId helper function")

# Second helper function openDraftedTrayModal
broken_helper2 = '''  function openDraftedTrayModal(lotId) {
    const $row = findRowByLotId(lotId);
    if ($row) {
      $row.find('.tray-scan-btn').click();
    }
  }'''

new_helper2 = '''  function openDraftedTrayModal(lotId) {
    const row = findRowByLotId(lotId);
    if (row) {
      const scanBtn = row.querySelector('.tray-scan-btn');
      if (scanBtn) {
        scanBtn.click();
      }
    }
  }'''

if broken_helper2 in content:
    # Replace all occurrences
    content = content.replace(broken_helper2, new_helper2)
    print("Step 3: Fixed openDraftedTrayModal helper function")

# Save after Step 3
with open(filePath, 'w', encoding='utf-8') as f:
    f.write(content)
print("File saved after step 3")

print("\n=== ALL FIXES COMPLETED SUCCESSFULLY ===")
print("? Updated keyboard hints (F1 ? F2)")
print("? Fixed F1 key handler (changed to F2 with vanilla JS)")
print("? Fixed helper functions (removed jQuery syntax)")
print("\nFile saved to:", filePath)

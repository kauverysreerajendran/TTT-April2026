#!/usr/bin/env python3
import re

# Read the file
with open('static/templates/Day_Planning/DP_PickTable.html', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update keyboard hints text
content = content.replace(
    'F1: Scan | T+Enter: Tray Scan | Del+Enter: Delete | Arrows: Navigate | 1-9: Page | Esc: Close',
    'F2: Scan | T+Enter: Tray Scan | Del+Enter: Delete | Arrows: Navigate | 1-9: Page | Esc: Close'
)

# 2. Fix the broken F1 handler - find and replace the whole broken section
broken_f1 = '''    // Handle F1 key FIRST - show "Please scan" message next to scan button
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
      console.log('🔵 F1 key pressed - Showing "Please scan" message next to scan button');
      
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
      message.textContent = '📱 Please scan';
      message.style.left = (rect.right + 10) + 'px';
      message.style.top = (rect.top + window.scrollY) + 'px';
      document.body.appendChild(message);
      
      // Remove message after animation completes (2 seconds)
      setTimeout(() => {
        message.remove();
      }, 2000);
      
      return;
    }'''

new_f2 = '''    // Handle F2 key FIRST - show "Please scan" message next to scan button
    if (e.key === 'F2') {
      e.preventDefault();
      showKeyboardHint();
      console.log('🔵 F2 key pressed - Showing "Please scan" message next to scan button');
      
      // If no row selected, select first row
      if (!currentSelectedRow) {
        const rows = getDataRows();
        if (rows.length > 0) {
          selectRow(rows[0]);
        }
      }
      
      if (!currentSelectedRow) return;
      
      // Find the scan button in the selected row
      const scanBtn = currentSelectedRow.querySelector('.tray-scan-btn-styled');
      if (!scanBtn) return;
      
      // Get button position
      const rect = scanBtn.getBoundingClientRect();
      
      // Create and display message next to button
      const message = document.createElement('div');
      message.className = 'f1-please-scan-message';
      message.textContent = '📱 Please scan';
      message.style.left = (rect.right + 10) + 'px';
      message.style.top = (rect.top + window.scrollY) + 'px';
      document.body.appendChild(message);
      
      // Remove message after animation completes (2 seconds)
      setTimeout(() => {
        message.remove();
      }, 2000);
      
      return;
    }'''

if broken_f1 in content:
    content = content.replace(broken_f1, new_f2)
    print("✅ Fixed F1→F2 handler")
else:
    print("⚠️ Broken F1 handler not found in expected format")

# 3. Fix broken helper functions
broken_helpers = '''  function findRowByLotId(lotId) {
    let targetRow = null;
    #order-listing tbody tr.each(function() {
      const rowLotId = .find('.tray-scan-btn').data('lot-id');
      if (String(rowLotId) === String(lotId)) {
        targetRow = ;
        return false;
      }
    });
    return targetRow;
  }

  function openDraftedTrayModal(lotId) {
    const $row = findRowByLotId(lotId);
    if ($row) {
      $row.find('.tray-scan-btn').click();
    }
  }'''

new_helpers = '''  // Helper: Find row by lot ID (works across all pages in DOM)
  function findRowByLotId(lotId) {
    if (!lotId) return null;
    const rows = Array.from(table.querySelectorAll('tbody tr'));
    return rows.find(row => {
      const btn = row.querySelector('.tray-scan-btn-styled');
      return btn && btn.dataset.lotId === String(lotId);
    });
  }

  // Helper: Find and open modal for drafted tray ID
  function openDraftedTrayModal(lotId) {
    if (!lotId) {
      showInvalidMessage(document.querySelector('.tray-scan-btn-styled'), '❌ Scanned Tray ID not exists');
      return;
    }

    let row = findRowByLotId(lotId);

    if (!row) {
      console.log('⚠️ Tray ID not in current page - showing error');
      showInvalidMessage(document.querySelector('.tray-scan-btn-styled'), '❌ Scanned Tray ID not exists');
      return;
    }

    row.scrollIntoView({ behavior: 'smooth', block: 'center' });
    
    const trayScanBtn = row.querySelector('.tray-scan-btn-styled');
    if (trayScanBtn) {
      trayScanBtn.click();
      console.log('✅ Drafted tray modal opened for lot:', lotId);
    }
  }'''

# Try to find and replace - may need to search for just one instance
if broken_helpers in content:
    content = content.replace(broken_helpers, new_helpers)
    print("✅ Fixed helper functions")
else:
    print("⚠️ Broken helpers not found in exact format")

# Write back
with open('static/templates/Day_Planning/DP_PickTable.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ File updated successfully")
print("✅ F1 changed to F2")
print("✅ Keyboard hints updated")
print("✅ Helper functions fixed")

"""
Replace the view icon eye-button JS in AcceptTable, Completed, and RejectTable
to call the CONSOLIDATED /iqf/iqf_lot_details/ API and render all 3 sections.
"""
import re

BASE = r'a:\Workspace\Watchcase\TTT-Jan2026\static\templates\IQF'

# The unified replacement script that works for all 3 modal templates
NEW_SCRIPT = r'''
<script nonce="{{ csp_nonce }}">
    document.addEventListener("DOMContentLoaded", function () {
      document.querySelectorAll('.tray-scan-btn-Jig').forEach(function(link) {
        link.addEventListener('click', async function (e) {
          e.preventDefault();

          const modal = document.getElementById("trayScanModal_DayPlanning");
          const detailsDiv = document.getElementById("trayScanDetails_DayPlanning");
          const modalModelNo = document.getElementById("modalModelNo_DayPlanning");
          const modalLotQty = document.getElementById("modalLotQty");
          const modalMissingQty = document.getElementById("modalMissingQty");
          const modalPhysicalQty = document.getElementById("modalPhysicalQty");

          modal.dataset.batchId = link.getAttribute('data-batch-id');
          const modelNo = link.getAttribute('data-model-no');
          const stockLotId = link.getAttribute('data-stock-lot-id');
          const totalBatchQuantity = link.getAttribute('data-total-batch-quantity') || "0";
          const lotQty = link.getAttribute('data-lot-qty') || "0";
          const missingQty = link.getAttribute('data-missing-qty') || "0";
          const physicalQty = link.getAttribute('data-physical-qty') || "0";

          if (modalModelNo && modelNo) modalModelNo.textContent = modelNo;
          if (modalLotQty) modalLotQty.textContent = totalBatchQuantity || lotQty || '0';
          if (modalMissingQty) modalMissingQty.textContent = missingQty || '0';
          if (modalPhysicalQty) modalPhysicalQty.textContent = physicalQty || '0';

          const modalUserImg = modal.querySelector('.user-profile img');
          const modelImage = link.getAttribute('data-model-image');
          if (modalUserImg) modalUserImg.src = modelImage || "/static/assets/images/imagePlaceholder.jpg";

          // ===== Fetch from CONSOLIDATED API =====
          let accepted = [], rejected = [], delinked = [], summary = {};
          try {
            const resp = await fetch('/iqf/iqf_lot_details/?lot_id=' + encodeURIComponent(stockLotId), { credentials: 'same-origin' });
            const result = await resp.json();
            if (result.success) {
              accepted = result.accepted || [];
              rejected = result.rejected || [];
              delinked = result.delinked || [];
              summary = result.summary || {};
            }
          } catch (err) {
            console.error('Error fetching IQF lot details:', err);
          }

          // ===== Build modal HTML =====
          function esc(s) { return s == null ? '' : String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

          function buildSection(title, bgColor, textColor, badgeBg, badgeLabel, trays, startRow) {
            if (!trays.length) return { html: '', row: startRow };
            let h = '<tr style="background-color:'+bgColor+';font-weight:bold;"><td colspan="3" style="text-align:center;color:'+textColor+';padding:8px;">'+title+'</td></tr>';
            // Sort: top_tray first, then by tray_id
            let sorted = trays.slice().sort(function(a,b){ if(a.top_tray && !b.top_tray) return -1; if(!a.top_tray && b.top_tray) return 1; return (a.tray_id||'').localeCompare(b.tray_id||''); });
            let row = startRow;
            sorted.forEach(function(t){
              row++;
              let sno = t.top_tray ? row + ' (Top Tray)' : String(row);
              let badge = '<span style="background:'+badgeBg+';color:white;padding:2px 6px;border-radius:10px;font-size:10px;margin-left:5px;">'+badgeLabel+'</span>';
              h += '<tr'+(t.top_tray?' class="top-tray-row" style="background:#e3f2fd;"':'')+'>';
              h += '<td>'+sno+'</td>';
              h += '<td><input type="text" class="form-control" value="'+esc(t.tray_id)+'" readonly style="width:100%;" />'+badge+'</td>';
              h += '<td><input type="number" class="form-control" value="'+(t.qty||0)+'" readonly style="width:100%;" /></td>';
              h += '</tr>';
            });
            return { html: h, row: row };
          }

          function buildTableHTML() {
            let html = '<table class="table table-bordered table-sm" style="width:100%;margin-bottom:0;"><thead><tr><th style="width:50px;">S.no</th><th>Tray ID</th><th>Tray Qty</th></tr></thead><tbody>';

            // Summary chips
            html += '<tr><td colspan="3" style="padding:8px;">';
            html += '<div style="display:flex;gap:8px;flex-wrap:wrap;">';
            html += '<span style="padding:3px 10px;border-radius:8px;background:#e8f5e9;color:#2e7d32;font-size:12px;font-weight:600;">Accepted: '+(summary.accepted_qty||0)+'</span>';
            html += '<span style="padding:3px 10px;border-radius:8px;background:#ffebee;color:#c62828;font-size:12px;font-weight:600;">Rejected: '+(summary.rejected_qty||0)+'</span>';
            html += '<span style="padding:3px 10px;border-radius:8px;background:#f5f5f5;color:#616161;font-size:12px;font-weight:600;">Delinked: '+(summary.delink_qty||0)+'</span>';
            html += '<span style="padding:3px 10px;border-radius:8px;background:#e3f2fd;color:#1565c0;font-size:12px;font-weight:600;">Incoming: '+(summary.iqf_incoming_qty||0)+'</span>';
            html += '</div>';
            if (summary.status_label) {
              let lC = summary.status_label==='ACCEPT'?'#2e7d32':summary.status_label==='REJECT'?'#c62828':summary.status_label==='PARTIAL'?'#e65100':'#616161';
              html += '<div style="margin-top:6px;"><span style="background:'+lC+'22;color:'+lC+';padding:2px 10px;border-radius:10px;font-size:11px;font-weight:700;border:1px solid '+lC+'44;">'+esc(summary.status_label)+'</span></div>';
            }
            html += '</td></tr>';

            let row = 0;
            let sec;

            sec = buildSection('\u2705 ACCEPTED TRAYS', '#e8f5e8', '#2e7d32', '#4caf50', 'ACCEPTED', accepted, row);
            html += sec.html; row = sec.row;

            sec = buildSection('\u274c REJECTED TRAYS', '#ffebee', '#c62828', '#f44336', 'REJECTED', rejected, row);
            html += sec.html; row = sec.row;

            sec = buildSection('\ud83d\udd17 DELINKED TRAYS', '#f8f9fa', '#6c757d', '#9e9e9e', 'DELINKED', delinked, row);
            html += sec.html; row = sec.row;

            if (!accepted.length && !rejected.length && !delinked.length) {
              html += '<tr><td colspan="3" style="text-align:center;padding:20px;color:#666;"><i class="fa fa-info-circle" style="margin-right:8px;"></i>No tray data found for this lot.</td></tr>';
            }

            if (summary.remarks) {
              html += '<tr><td colspan="3" style="font-size:12px;color:#666;"><strong>Remarks:</strong> '+esc(summary.remarks)+'</td></tr>';
            }

            html += '</tbody></table>';
            return html;
          }

          detailsDiv.innerHTML = buildTableHTML();

          modal.buildTableHTML = buildTableHTML;
          modal.traysData = { accepted: accepted, rejected: rejected, delinked: delinked };
          modal.rejectionSummary = summary;

          modal.style.display = "block";
          modal.classList.add("open");
        });
      });

      const closeBtn = document.getElementById("closeTrayScanModal_DayPlanning");
      if (closeBtn) {
        closeBtn.addEventListener("click", function () {
          const modal = document.getElementById("trayScanModal_DayPlanning");
          if (modal) { modal.classList.remove("open"); modal.style.display = "none"; }
        });
      }
    });
</script>'''

# Pattern: find the script block that starts after "Tray validation script setup complete"
# and contains '.tray-scan-btn-Jig' click handler, ending with the close handler </script>

files = [
    (BASE + r'\Iqf_AcceptTable.html', 'AcceptTable'),
    (BASE + r'\Iqf_Completed.html', 'Completed'),
    (BASE + r'\Iqf_RejectTable.html', 'RejectTable'),
]

for filepath, label in files:
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Find the anchor: end of "Tray validation script setup complete" block
    anchor = 'console.log("\U0001f3af Tray validation script setup complete");'
    anchor_idx = content.find(anchor)
    if anchor_idx == -1:
        # Try alternate anchor
        anchor = 'Tray validation script setup complete'
        anchor_idx = content.find(anchor)
    
    if anchor_idx == -1:
        print(f"SKIP {label}: Could not find anchor marker")
        continue

    # Find the </script> that closes the anchor block
    anchor_script_end = content.find('</script>', anchor_idx)
    if anchor_script_end == -1:
        print(f"SKIP {label}: Could not find </script> after anchor")
        continue
    anchor_block_end = anchor_script_end + len('</script>')

    # Now find the NEXT <script> block that contains 'tray-scan-btn-Jig'
    next_script_start = content.find('<script', anchor_block_end)
    if next_script_start == -1 or 'tray-scan-btn-Jig' not in content[next_script_start:next_script_start+5000]:
        print(f"SKIP {label}: Next script block doesn't contain tray-scan-btn-Jig")
        continue

    # Find the end of this script block.
    # The block ends with the close handler pattern: closeTrayScanModal_DayPlanning ... });\n</script>
    close_marker = "closeTrayScanModal_DayPlanning"
    close_idx = content.find(close_marker, next_script_start)
    if close_idx == -1:
        print(f"SKIP {label}: Could not find close modal marker")
        continue

    # Find the </script> that ends this block
    view_script_end = content.find('</script>', close_idx)
    if view_script_end == -1:
        print(f"SKIP {label}: Could not find closing </script>")
        continue
    block_end = view_script_end + len('</script>')

    old_block = content[next_script_start:block_end]

    # Replace
    content = content[:next_script_start] + NEW_SCRIPT + content[block_end:]

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"OK {label}: Replaced {len(old_block)} chars with {len(NEW_SCRIPT)} chars")

print("\nAll done.")

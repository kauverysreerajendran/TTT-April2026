"""Replace the PickTable view icon JS block with consolidated API version."""
import os

FILE = r'a:\Workspace\Watchcase\TTT-Jan2026\static\templates\IQF\Iqf_PickTable.html'

with open(FILE, 'r', encoding='utf-8') as fh:
    content = fh.read()

OLD_START = '<!-- IQF: UI-only view icon handler'
OLD_END_MARKER = '<!-- RW Qty - Checkbox'

start_idx = content.index(OLD_START)
end_idx = content.index(OLD_END_MARKER, start_idx)
script_end = content.rfind('</script>', start_idx, end_idx)
block_end = script_end + len('</script>')

old_block = content[start_idx:block_end]
print(f"Found old block: {len(old_block)} chars, lines approx {content[:start_idx].count(chr(10))+1}")

NEW_BLOCK = r'''<!-- IQF: View icon handler — calls CONSOLIDATED API, shows ALL sections (accepted, rejected, delinked). -->
<script nonce="{{ csp_nonce }}">
(function(){
  function escapeHtml(s){ if(s===null||s===undefined) return ''; return String(s).replace(/[&<>"']/g, function(m){ return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]; }); }

  function buildSection(title, color, icon, trays, startIdx){
    if(!trays || !trays.length) return {html:'', nextIdx: startIdx};
    var html = '<div style="margin:12px 0 6px;font-weight:700;font-size:13px;color:'+color+';"><i class="fa '+icon+'" style="margin-right:4px;"></i>'+escapeHtml(title)+' ('+trays.length+')</div>';
    html += '<table style="width:100%;border-collapse:collapse;">';
    html += '<thead><tr><th style="text-align:left;padding:6px 8px;border-bottom:2px solid '+color+';font-weight:600;font-size:12px;">S.No</th><th style="text-align:left;padding:6px 8px;border-bottom:2px solid '+color+';font-weight:600;font-size:12px;">Tray ID</th><th style="text-align:right;padding:6px 8px;border-bottom:2px solid '+color+';font-weight:600;font-size:12px;">Qty</th><th style="text-align:center;padding:6px 8px;border-bottom:2px solid '+color+';font-weight:600;font-size:12px;">Status</th></tr></thead><tbody>';
    var idx = startIdx;
    trays.forEach(function(t){
      idx++;
      var badge = '';
      if(t.top_tray) badge = ' <span style="background:#e3f2fd;color:#1565c0;padding:1px 6px;border-radius:8px;font-size:10px;font-weight:600;">Top</span>';
      var statusBadge = '<span style="background:'+(t.status==='ACCEPT'?'#e8f5e9;color:#2e7d32':t.status==='REJECT'?'#ffebee;color:#c62828':'#f5f5f5;color:#616161')+';padding:2px 8px;border-radius:8px;font-size:11px;font-weight:600;">'+escapeHtml(t.status)+'</span>';
      html += '<tr style="border-bottom:1px solid #f0f0f0;"><td style="padding:6px 8px;">'+idx+'</td><td style="padding:6px 8px;">'+escapeHtml(t.tray_id)+badge+'</td><td style="padding:6px 8px;text-align:right;font-weight:600;">'+escapeHtml(String(t.qty||0))+'</td><td style="padding:6px 8px;text-align:center;">'+statusBadge+'</td></tr>';
    });
    html += '</tbody></table>';
    return {html: html, nextIdx: idx};
  }

  function openTrayView(btn){
    if(!btn) return;
    var modal = document.getElementById('trayViewModal');
    var content = document.getElementById('trayViewContent');
    try{
      var lotId = btn.getAttribute('data-stock-lot-id') || btn.dataset.stockLotId || '';
      var modelNo = btn.getAttribute('data-model-no') || btn.dataset.modelNo || '';

      content.innerHTML = '<div style="padding:20px;text-align:center;">Loading tray details...</div>';
      if(modal){ modal.style.right = '0'; modal.setAttribute('aria-hidden','false'); }

      fetch('/iqf/iqf_lot_details/?lot_id=' + encodeURIComponent(lotId), { credentials: 'same-origin' })
        .then(function(res){ return res.json().catch(function(){ return { success: false, error: 'invalid json' }; }); })
        .then(function(data){
          if(!data || !data.success){
            content.innerHTML = '<div style="padding:16px;color:#999;">No tray details available</div>';
            return;
          }

          try{ var modelSpan = document.getElementById('trayViewModelNo'); if(modelSpan) modelSpan.textContent = modelNo || ''; }catch(e){}

          var s = data.summary || {};
          var html = '';
          html += '<div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px;">';
          html += '<div style="padding:4px 10px;border-radius:8px;background:#e8f5e9;color:#2e7d32;font-size:12px;font-weight:600;">Accepted: '+escapeHtml(String(s.accepted_qty||0))+'</div>';
          html += '<div style="padding:4px 10px;border-radius:8px;background:#ffebee;color:#c62828;font-size:12px;font-weight:600;">Rejected: '+escapeHtml(String(s.rejected_qty||0))+'</div>';
          html += '<div style="padding:4px 10px;border-radius:8px;background:#f5f5f5;color:#616161;font-size:12px;font-weight:600;">Delinked: '+escapeHtml(String(s.delink_qty||0))+'</div>';
          html += '<div style="padding:4px 10px;border-radius:8px;background:#e3f2fd;color:#1565c0;font-size:12px;font-weight:600;">Incoming: '+escapeHtml(String(s.iqf_incoming_qty||0))+'</div>';
          html += '</div>';

          if(s.status_label){
            var lblColor = s.status_label==='ACCEPT'?'#2e7d32':s.status_label==='REJECT'?'#c62828':s.status_label==='PARTIAL'?'#e65100':'#616161';
            html += '<div style="margin-bottom:10px;"><span style="background:'+lblColor+'22;color:'+lblColor+';padding:3px 12px;border-radius:12px;font-size:12px;font-weight:700;border:1px solid '+lblColor+'44;">'+escapeHtml(s.status_label)+'</span></div>';
          }

          var idx = 0;
          var sec;
          sec = buildSection('Accepted Trays', '#2e7d32', 'fa-check-circle', data.accepted, idx);
          html += sec.html; idx = sec.nextIdx;
          sec = buildSection('Rejected Trays', '#c62828', 'fa-times-circle', data.rejected, idx);
          html += sec.html; idx = sec.nextIdx;
          sec = buildSection('Delinked Trays', '#616161', 'fa-unlink', data.delinked, idx);
          html += sec.html; idx = sec.nextIdx;

          if(!data.accepted.length && !data.rejected.length && !data.delinked.length){
            html += '<div style="padding:16px;text-align:center;color:#999;">No trays recorded for this lot</div>';
          }

          if(s.remarks){ html += '<div style="margin-top:10px;font-size:12px;color:#666;"><strong>Remarks:</strong> '+escapeHtml(s.remarks)+'</div>'; }

          content.innerHTML = html;
        }).catch(function(err){ console.error('tray fetch failed', err); content.innerHTML = '<div style="padding:16px;color:#c62828;">Failed to load trays</div>'; });
    }catch(err){ console.error('openTrayView failed', err); }
  }

  document.addEventListener('click', function(e){
    var btn = e.target.closest && e.target.closest('.tray-scan-btn-Jig');
    if(btn){
      e.preventDefault();
      openTrayView(btn);
      return;
    }
    if(e.target && e.target.id === 'trayViewClose'){
      var modal = document.getElementById('trayViewModal'); if(modal){ modal.style.right='-420px'; modal.setAttribute('aria-hidden','true'); }
    }
    if(e.target && e.target.id === 'trayViewModal'){
      var modal = document.getElementById('trayViewModal'); if(modal){ modal.style.right='-420px'; modal.setAttribute('aria-hidden','true'); }
    }
  });

})();
</script>'''

content = content[:start_idx] + NEW_BLOCK + content[block_end:]

with open(FILE, 'w', encoding='utf-8') as fh:
    fh.write(content)

print(f"SUCCESS: Replaced {len(old_block)} chars with {len(NEW_BLOCK)} chars")

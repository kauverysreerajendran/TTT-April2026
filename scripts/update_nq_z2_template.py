"""Script to update Z2 template with new NQ JS block (Z2 API_BASE)."""
z1_path = 'static/templates/Nickel_Inspection/Nickel_PickTable.html'
z2_path = r'static/templates/Nickel_Inspection - Zone_two/Nickel_PickTable_zone_two.html'

with open(z1_path, 'r', encoding='utf-8') as f:
    z1 = f.read()

with open(z2_path, 'r', encoding='utf-8') as f:
    z2 = f.read()

shortcuts_tag = "<script nonce=\"{{ csp_nonce }}\" src=\"{% static 'js/nickel_qc_shortcuts.js' %}\"></script>"
js_block_start = z1.find(shortcuts_tag)
if js_block_start == -1:
    print('ERROR: shortcuts tag not found in Z1')
    exit(1)

endblock = '{% endblock %} {% endblock content %}'
endblock_pos = z1.rfind(endblock)

new_js_block = z1[js_block_start:endblock_pos]
print('New JS block start (first 100):', repr(new_js_block[:100]))
print('New JS block end (last 100):', repr(new_js_block[-100:]))

new_js_block_z2 = new_js_block.replace(
    "var API_BASE = '/nickle_inspection/api/';",
    "var API_BASE = '/nickle_inspection_zone_two/api/';",
)

old_js_start_marker = '<!-- NQ Checkbox + Reject Modal JS -->'
old_start = z2.find(old_js_start_marker)
old_endblock_pos = z2.rfind(endblock)

print('Z2 old JS start:', old_start)
print('Z2 endblock pos:', old_endblock_pos)

new_z2 = z2[:old_start] + new_js_block_z2 + z2[old_endblock_pos:]
with open(z2_path, 'w', encoding='utf-8') as f:
    f.write(new_z2)
print('Done. Z2 file length:', len(new_z2))

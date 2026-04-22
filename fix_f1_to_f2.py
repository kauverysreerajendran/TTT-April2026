#!/usr/bin/env python3
import re

# Read the file
with open('static/templates/Day_Planning/DP_PickTable.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace F1 with F2 in the key check
content = re.sub(
    r"if \(e\.key === 'F1'\) \{",
    "if (e.key === 'F2') {",
    content
)

# Fix querySelector references from .tray-scan-btn to .tray-scan-btn-styled
content = content.replace(
    "currentSelectedRow.querySelector('.tray-scan-btn')",
    "currentSelectedRow.querySelector('.tray-scan-btn-styled')"
)

# Remove the broken jQuery lines and keep only the vanilla JS code
# Strategy: Remove lines with jQuery syntax (.find, <div>, .data, .parent, .css)

lines = content.split('\n')
new_lines = []
skip_until_closing_brace = False
brace_count = 0
in_broken_section = False

for i, line in enumerate(lines):
    # Check if this line has the broken jQuery code pattern
    if "const btn = .find('.tray-scan-btn');" in line:
        in_broken_section = True
        skip_until_closing_brace = True
        brace_count = 0
        continue
    
    # If we're in a broken section, track braces and skip lines until the if block closes
    if skip_until_closing_brace:
        # Count braces
        brace_count += line.count('{')
        brace_count -= line.count('}')
        
        # Skip lines in the broken block
        if "const isDrafted" in line or ".data('draft-saved')" in line or ".parent().css" in line or "const $msg" in line:
            continue
        if "setTimeout(() => $msg.remove()" in line:
            skip_until_closing_brace = False
            continue
    
    new_lines.append(line)

content = '\n'.join(new_lines)

# Write back
with open('static/templates/Day_Planning/DP_PickTable.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Fixed F1→F2 handler")
print("✅ Cleaned up jQuery code")
print("✅ Updated querySelector selectors")

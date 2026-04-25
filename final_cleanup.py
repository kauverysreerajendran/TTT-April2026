#!/usr/bin/env python
"""Comprehensive blank line removal for Nickel view files."""

import re

def aggressive_blank_line_cleanup(filepath):
    """
    Remove all excessive blank lines while preserving single blank lines
    between logical sections (classes, functions).
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Step 1: Replace ALL sequences of 2+ newlines with exactly 2 newlines
    content = re.sub(r'\n\n\n+', '\n\n', content)
    
    # Step 2: Remove blank lines between imports (consecutive import/from statements)
    lines = content.split('\n')
    result = []
    i = 0
    
    while i < len(lines):
        line = lines[i]
        result.append(line)
        
        # If this is an import/from line, skip any following blank lines
        # but only if the next non-blank line is also an import
        if line.strip().startswith(('from ', 'import ')):
            j = i + 1
            blank_lines_to_skip = []
            
            while j < len(lines) and lines[j].strip() == '':
                blank_lines_to_skip.append(j)
                j += 1
            
            # Check if next non-blank line is also an import
            if j < len(lines) and lines[j].strip().startswith(('from ', 'import ')):
                # Skip the blank lines
                i = j - 1
        
        i += 1
    
    # Step 3: Replace back to string
    final_content = '\n'.join(result)
    
    # Step 4: Ensure file ends with single newline
    final_content = final_content.rstrip() + '\n'
    
    # Step 5: Write back
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(final_content)
    
    final_lines = final_content.split('\n')
    return len(final_lines)

print("🔧 Aggressive cleanup in progress...\n")

lines_z1 = aggressive_blank_line_cleanup('Nickel_Inspection/views.py')
print(f"✅ Zone 1 (Nickel_Inspection/views.py): Reduced to {lines_z1} lines")

lines_z2 = aggressive_blank_line_cleanup('nickel_inspection_zone_two/views.py')
print(f"✅ Zone 2 (nickel_inspection_zone_two/views.py): Reduced to {lines_z2} lines")

print("\n✅ CLEANUP COMPLETE!")
print(f"   Total reduction: {lines_z1 + lines_z2} lines for both files")

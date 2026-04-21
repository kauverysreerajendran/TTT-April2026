import re
import os

def process_file(filepath):
    print(f"Processing {filepath}...")
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Pattern for the "isBatchRejection" block
    p1 = r'if \(isBatchRejection\) \{[\s\n]*\/\/ Always fetch accepted tray scan data to get latest is_delink_only status[\s\n]*fetch\(`/nickle_inspection/nickel_get_accepted_tray_scan_data/.*?\)\s*\.then\(res => res\.json\(\)\)\s*\.then\(rescanData => \{(?:[^{}]*|\{(?:[^{}]*|\{[^{}]*\})*\})*\}\);[\s\n]*\}'
    
    # Pattern for "isOnHold" block - using a more robust regex for the block
    p2 = r'\}else if \(isOnHold\) \{[\s\S]*?fetch\(`/nickle_inspection/nickel_get_accepted_tray_scan_data/.*?\)\s*\.then\(res => res\.json\(\)\)\s*\.then\(rescanData => \{(?:[^{}]*|\{(?:[^{}]*|\{[^{}]*\})*\})*\}\);[\s\n]*\}'

    # Pattern for the "Always fetch... " block at the end (btn.getAttribute('data-stock-lot-id'))
    p3 = r'\/\/ Always fetch accepted tray scan data to get latest is_delink_only status[\s\n]*fetch\(`/nickle_inspection/nickel_get_accepted_tray_scan_data/.*?\)\s*\.then\(res => res\.json\(\)\)\s*\.then\(rescanData => \{(?:[^{}]*|\{(?:[^{}]*|\{[^{}]*\})*\})*\}\);'

    # We want to keep the one inside fetchAndShowAcceptedTrayData and the one inside handleRejectionSubmit (after submit)
    
    new_content = content
    
    # Replacement for p1: Just comment it out
    matches1 = re.findall(p1, new_content, re.DOTALL)
    for m in matches1:
        print("Found p1 match")
        new_content = new_content.replace(m, "/* PRE-FETCH REMOVED (isBatchRejection) */")

    # Replacement for p2: Comment inside the else if
    matches2 = re.findall(p2, new_content, re.DOTALL)
    for m in matches2:
        print("Found p2 match")
        new_content = new_content.replace(m, "} else if (isOnHold) { /* PRE-FETCH REMOVED (isOnHold) */ }")

    # Replacement for p3: Comment it
    matches3 = re.findall(p3, new_content, re.DOTALL)
    for m in matches3:
        # Check context to make sure it's not the one we want to keep?
        # The prompt says: "Remove or comment out those pre-fetch calls (the ones that fetch accepted trays on button click, BEFORE user enters reject qty)"
        # The one inside fetchAndShowAcceptedTrayData doesn't have the comment "Always fetch..." above it usually.
        print("Found p3 match")
        new_content = new_content.replace(m, "/* PRE-FETCH REMOVED (btn click) */")

    if new_content != content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        return True
    return False

files = [
    r'static\templates\Nickel_Inspection\Nickel_PickTable.html',
    r'static\templates\Nickel_Inspection - Zone_two\Nickel_PickTable_zone_two.html'
]

for f in files:
    if os.path.exists(f):
        changed = process_file(f)
        print(f"{f}: {'Changed' if changed else 'No changes'}")
    else:
        print(f"File not found: {f}")

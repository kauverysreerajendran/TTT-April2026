import re
import os

def process_file(filepath):
    print(f"Processing {filepath}...")
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Generic pattern to match fetch blocks that call 'nickel_get_accepted_tray_scan_data'
    # and have a .then(res => res.json()).then(rescanData => { ... })
    # Using a simpler matching approach for the block
    pattern = r'fetch\(`/nickle_inspection/nickel_get_accepted_tray_scan_data/.*?\)\s*\.then\(res => res\.json\(\)\)\s*\.then\(rescanData => \{(?:[^{}]*|\{(?:[^{}]*|\{[^{}]*\})*\})*\}\)'

    new_content = content
    matches = list(re.finditer(pattern, content, re.DOTALL))
    
    # We want to keep the one inside fetchAndShowAcceptedTrayData or inside a submit handler.
    # From context, the ones to remove are at indices 0, 1, and 4 (in the 5 match case).
    # Let's check context for phrases:
    # 0: "if (isBatchRejection)"
    # 1: "else if (isOnHold)"
    # 2: "function fetchAndShowAcceptedTrayData" <- KEEP
    # 3: "console.log(... Available=...)" (Inside submit) <- KEEP
    # 4: "Always fetch accepted tray scan data to get latest is_delink_only status" (On button click)
    
    # Let's iterate backwards to not mess up indices
    for m in reversed(matches):
        start = m.start()
        # Peek before the match
        context_before = content[max(0, start-150):start]
        
        should_remove = False
        if "isBatchRejection" in context_before:
            should_remove = True
        elif "isOnHold" in context_before:
            should_remove = True
        elif "Always fetch accepted tray scan data" in context_before:
            should_remove = True
            
        if should_remove:
            print(f"Removing match at {start}")
            # Identify if it's inside an 'else if (isOnHold)' to preserve structure
            if "else if (isOnHold)" in context_before[-50:]:
                 new_content = new_content[:start] + "/* REMOVED PRE-FETCH */" + new_content[m.end():]
            else:
                 new_content = new_content[:start] + "/* REMOVED PRE-FETCH */" + new_content[m.end():]

    if new_content != content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        return True
    return False

files = [
    r'static/templates/Nickel_Inspection/Nickel_PickTable.html',
    r'static/templates/Nickel_Inspection - Zone_two/Nickel_PickTable_zone_two.html'
]

for f in files:
    if os.path.exists(f):
        changed = process_file(f)
        print(f"{f}: {'Changed' if changed else 'No changes'}")
    else:
        print(f"File not found: {f}")

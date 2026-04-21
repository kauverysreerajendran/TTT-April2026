import re

def process_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Pattern to match the fetch blocks that occur BEFORE rejection is entered.
    # We want to keep the one inside fetchAndShowAcceptedTrayData and the one that happens after submission.
    
    # 1. Look for the block that happens on button click (often inside a click handler or checking isBatchRejection)
    # The prompt says: "Remove or comment out those pre-fetch calls (the ones that fetch accepted trays on button click, BEFORE user enters reject qty)"
    
    # Let's target specific patterns seen in the grep output:
    # Pattern A: if (isBatchRejection) { ... fetch(...) ... }
    # Pattern B: }else if (isOnHold) { ... fetch(...) ... }
    # Pattern C: Always fetch accepted tray scan data to get latest is_delink_only status ... fetch(...)
    
    # Substantial blocks often look like:
    # fetch(...)
    #   .then(res => res.json())
    #   .then(rescanData => {
    #     if (rescanData.success && rescanData.is_delink_only) { ... }
    #   })

    # We use non-greedy matching and multiline
    # Replacing with a comment
    
    # Regex for "isBatchRejection" or "Always fetch... is_delink_only" or "isOnHold" blocks
    
    # Pattern 1: Always fetch accepted tray scan data to get latest is_delink_only status
    p1 = r'\/\/\s*Always fetch accepted tray scan data to get latest is_delink_only status\s*fetch\(/nickle_inspection/nickel_get_accepted_tray_scan_data/.*?\)\s*\.then\(res => res\.json\(\)\)\s*\.then\(rescanData => \{(?:[^{}]*|\{(?:[^{}]*|\{[^{}]*\})*\})*\}\)'
    
    # Pattern 2: isOnHold block
    p2 = r'\}else if \(isOnHold\) \{[\s\S]*?\/\/ Directly fetch and show accepted tray data[\s\S]*?fetch\(/nickle_inspection/nickel_get_accepted_tray_scan_data/.*?\)\s*\.then\(res => res\.json\(\)\)\s*\.then\(rescanData => \{(?:[^{}]*|\{(?:[^{}]*|\{[^{}]*\})*\})*\}\)'

    new_content = content
    
    matches1 = re.findall(p1, new_content, re.DOTALL)
    for m in matches1:
        new_content = new_content.replace(m, "/* Pre-fetch removed: " + m[:50].replace("*/", "* /") + "... */")
        
    matches2 = re.findall(p2, new_content, re.DOTALL)
    for m in matches2:
         # We need to be careful with the 'else if' part. Let's keep the structure but comment the inside?
         # Or just comment the whole block if it was just for the fetch.
         new_content = new_content.replace(m, "} else if (isOnHold) { /* Pre-fetch removed */ }")

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
    changed = process_file(f)
    print(f"{f}: {'Changed' if changed else 'No changes'}")

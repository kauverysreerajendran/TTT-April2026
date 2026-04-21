import os

def clean_file(filepath):
    print(f"Cleaning {filepath}...")
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    new_lines = []
    skip = False
    open_braces = 0
    count = 0
    
    for line in lines:
        # Detect the start of a removal block
        if not skip:
            if ("fetch(`/nickle_inspection/nickel_get_accepted_tray_scan_data/" in line) and \
               ("isBatchRejection" in "".join(new_lines[-5:]) or \
                "isOnHold" in "".join(new_lines[-5:]) or \
                "Always fetch accepted tray scan data" in "".join(new_lines[-5:])):
                
                print(f"Start skipping at line: {line.strip()[:40]}")
                skip = True
                open_braces = line.count('{') - line.count('}')
                new_lines.append("/* PRE-FETCH REMOVED */\n")
                continue
            
        if skip:
            open_braces += line.count('{') - line.count('}')
            if open_braces <= 0:
                skip = False
            continue
            
        new_lines.append(line)

    with open(filepath, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)
    return True

files = ["static/templates/Nickel_Inspection/Nickel_PickTable.html", "static/templates/Nickel_Inspection - Zone_two/Nickel_PickTable_zone_two.html"]
for f in files:
    if os.path.exists(f):
        clean_file(f)

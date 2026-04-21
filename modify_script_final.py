import os

def modify_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    new_lines = []
    i = 0
    found_process = False
    modified = False
    
    while i < len(lines):
        line = lines[i]
        if "if action == 'PROCESS':" in line:
            found_process = True
            new_lines.append(line)
            i += 1
            continue
        
        if found_process:
            if "if not tray_actions:" in line:
                i += 3 
                continue
            
            if "rejected_qty = sum(" in line:
                indent = line[:line.find('rejected_qty')]
                new_lines.append(f"{indent}rejected_qty = sum(int(r.get('rejected_qty', 0)) for r in rejection_reasons)\n")
                new_lines.append(f"{indent}delink_qty = sum(int(t.get('qty', 0)) for t in tray_actions if t.get('action') == 'delink')\n")
                new_lines.append(f"{indent}accepted_qty = total_qty - rejected_qty - delink_qty\n")
                new_lines.append(f"{indent}if accepted_qty < 0:\n")
                new_lines.append(f"{indent}    return JsonResponse({{'success': False, 'error': f'Invalid quantities: Accepted ({{accepted_qty}}) cannot be negative'}}, status=400)\n")
                
                while i < len(lines) and "if rejected_qty <= 0:" not in lines[i]:
                    i += 1
                i += 2 
                found_process = False 
                modified = True
                continue
        
        new_lines.append(line)
        i += 1
    
    if modified:
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.writelines(new_lines)
        print(f'Successfully modified {path}')
    else:
        print(f'Failed to modify {path}')

modify_file('Nickel_Inspection/views.py')
modify_file('nickel_inspection_zone_two/views.py')

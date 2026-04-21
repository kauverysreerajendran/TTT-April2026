import os

def modify_views_file(file_path):
    print(f"Processing {file_path}...")
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    modified = False
    new_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # 1. Look for 'if action == '\''PROCESS'\'':'
        if \"if action == 'PROCESS':\" in line:
            new_lines.append(line)
            i += 1
            # Skip until we find validation or calculation
            while i < len(lines):
                inner_line = lines[i]
                
                # Check for: if not tray_actions:
                if \"if not tray_actions:\" in inner_line:
                    print(f"Removing 'if not tray_actions' at line {i+1}")
                    # Skip the next 2 lines (the if block)
                    i += 3 
                    continue
                
                # Look for rejected_qty calculation
                if \"rejected_qty = sum(\" in inner_line or \"rejected_qty = 0\" in inner_line:
                    # We found the qty calculations
                    # Let's find where they are and replace the block
                    
                    # Gather the original qty calculation and validation block
                    qty_block_start = i
                    while i < len(lines) and not (\"if rejected_qty <= 0:\" in lines[i]):
                        i += 1
                    
                    if i < len(lines) and \"if rejected_qty <= 0:\" in lines[i]:
                        print(f"Found rejected_qty validation at line {i+1}")
                        
                        # We want to replace the block from qty_block_start to the end of validation
                        # But let's be precise.
                        
                        # Extract indentation
                        indent = \" \" * (len(lines[qty_block_start]) - len(lines[qty_block_start].lstrip()))
                        
                        # Add new logic
                        new_lines.append(f\"{indent}rejected_qty = sum(int(r.get('rejected_qty', 0)) for r in rejection_reasons)\n\")
                        new_lines.append(f\"{indent}delink_qty = sum(int(t.get('qty', 0)) for t in tray_actions if t.get('action') == 'delink')\n\")
                        new_lines.append(f\"{indent}accept_qty = total_qty - rejected_qty - delink_qty\n\")
                        new_lines.append(f\"{indent}if accept_qty < 0:\n\")
                        new_lines.append(f\"{indent}    return JsonResponse({{'success': False, 'error': f'Invalid quantities: Accept ({{accept_qty}}) cannot be negative'}}, status=400)\n\")
                        
                        # Skip original validation block (if rejected_qty <= 0 and its body)
                        # The original block usually is:
                        # if rejected_qty <= 0:
                        #     return JsonResponse(...)
                        i += 2 
                        modified = True
                        break
                
                new_lines.append(inner_line)
                i += 1
                
                # If we hit the end of PROCESS section, break
                if i < len(lines) and (\"if action ==\" in lines[i] or \"return JsonResponse\" in lines[i] and \"Unknown action\" in lines[i]):
                    break
            continue

        new_lines.append(line)
        i += 1

    if modified:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
        print(f"Successfully modified {file_path}")
    else:
        print(f"Could not find modification points in {file_path}")

modify_views_file('Nickel_Inspection/views.py')
modify_views_file('nickel_inspection_zone_two/views.py')

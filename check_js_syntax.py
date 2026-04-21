import re, subprocess, os, tempfile

filepath = 'static/templates/Nickel_Inspection - Zone_two/Nickel_PickTable_zone_two.html'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

lines = content.split('\n')
in_script = False
script_blocks = []
current_block = []
start_line = 0

for i, line in enumerate(lines):
    if '<script' in line.lower() and '</script>' not in line.lower():
        in_script = True
        start_line = i + 1
        current_block = []
    elif '</script>' in line.lower() and in_script:
        in_script = False
        script_blocks.append((start_line, '\n'.join(current_block)))
    elif in_script:
        current_block.append(line)

print(f"Found {len(script_blocks)} script blocks")

for idx, (start, block) in enumerate(script_blocks):
    # Remove Django template tags
    cleaned = re.sub(r'\{\{.*?\}\}', '"TEMPLATE_VAR"', block)
    cleaned = re.sub(r'\{%.*?%\}', '', cleaned)
    
    tmp = os.path.join(tempfile.gettempdir(), f'block_{idx}.js')
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(cleaned)
    
    check_script = f'''
try {{
    new Function(require("fs").readFileSync("{tmp.replace(os.sep, '/')}", "utf-8"));
}} catch(e) {{
    console.log("SYNTAX ERROR in Block {idx} (starts at source line {start}): " + e.message);
}}
'''
    check_file = os.path.join(tempfile.gettempdir(), f'check_{idx}.js')
    with open(check_file, 'w', encoding='utf-8') as f:
        f.write(check_script)
    
    result = subprocess.run(['node', check_file], capture_output=True, text=True, timeout=5)
    if result.stdout.strip():
        print(result.stdout.strip())

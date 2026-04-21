import io

def fix_file(filename, search_text, replace_text):
    with io.open(filename, "r", encoding="utf-8") as f:
        content = f.read()
    if search_text in content:
        new_content = content.replace(search_text, replace_text)
        with io.open(filename, "w", encoding="utf-8", newline="") as f:
            f.write(new_content)
        print(f"Fixed {filename}")
    else:
        print(f"Search text not found in {filename}")

fix_file("Nickel_Inspection/views.py", 
         "rejected_qty = sum(int(r.get('rejected_qty', 0)) for r in rejection_reasons)",
         "rejected_qty = sum(int(r.get('qty', 0)) for r in rejection_reasons)")

fix_file("nickel_inspection_zone_two/views.py", 
         "rejected_qty = sum(int(r.get('rejected_qty', 0)) for r in rejection_reasons)",
         "rejected_qty = sum(int(r.get('qty', 0)) for r in rejection_reasons)")

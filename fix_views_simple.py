import re
p2 = r"a:\Workspace\Watchcase\TTT-Jan2026\nickel_inspection_zone_two\views.py"
with open(p2, "rb") as f: content = f.read()
old = b"print(f\"\xf0\x9f\x93\xb8 NQ View - Final images for lot {jig_unload_obj.lot_id}: {len(images)} images\")\r\n\r\n\r\n\r\n\r\n\r\n            master_data.append(data)"
new = b"print(f\"\xf0\x9f\x93\xb8 NQ View - Final images for lot {jig_unload_obj.lot_id}: {len(images)} images\")\r\n\r\n            # Normalize tray_type display label (NR -> Normal)\r\n            if data.get(\"tray_type\") and data[\"tray_type\"].strip().lower() == \"nr\":\r\n                data[\"tray_type\"] = \"Normal\"\r\n\r\n            master_data.append(data)"
if content.count(old) == 1: content = content.replace(old, new); open(p2, "wb").write(content); print("Zone 2: FIXED")
p1 = r"a:\Workspace\Watchcase\TTT-Jan2026\Nickel_Inspection\views.py"
with open(p1, "rb") as f: content = f.read()
old = b"print(f\"\xf0\x9f\x93\xb8 NQ View - Final images for lot {jig_unload_obj.lot_id}: {len(images)} images\")\r\n\r\n\r\n\r\n\r\n\r\n\r\n\r\n\r\n\r\n\r\n\r\n\r\n\r\n\r\n\r\n            master_data.append(data)"
if content.count(old) == 1: content = content.replace(old, new); open(p1, "wb").write(content); print("Zone 1: FIXED")

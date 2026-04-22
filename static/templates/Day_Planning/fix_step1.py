# Read the file
filePath = r"a:\Workspace\Watchcase\TTT-Jan2026\static\templates\Day_Planning\DP_PickTable.html"
with open(filePath, "r", encoding="utf-8") as f:
    content = f.read()

print("File loaded. Content length:", len(content))

# Step 1: Update keyboard hints from F1 to F2
original_hints = "F1: Scan | T+Enter: Tray Scan | Del+Enter: Delete | Arrows: Navigate | 1-9: Page | Esc: Close"
new_hints = "F2: Scan | T+Enter: Tray Scan | Del+Enter: Delete | Arrows: Navigate | 1-9: Page | Esc: Close"
if original_hints in content:
    content = content.replace(original_hints, new_hints)
    print("✓ Step 1: Updated keyboard hints from F1 to F2")

# Save after Step 1
with open(filePath, "w", encoding="utf-8") as f:
    f.write(content)
print("✓ Keyboard hints updated and saved")

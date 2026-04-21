"""Quick analyzer to inspect inline <script> blocks for Django template tags."""
import re
from pathlib import Path

p = Path("static/templates/Input_Screening/IS_PickTable.html")
t = p.read_text(encoding="utf-8")
blocks = list(re.finditer(r"<script[^>]*>.*?</script>", t, re.DOTALL))
print(f"file len: {len(t)}, script blocks: {len(blocks)}")
for i, m in enumerate(blocks):
    body = m.group(0)
    tags = re.findall(r"\{%[^%]*%\}|\{\{[^}]*\}\}", body)
    print(f"--- block {i} (offset {m.start()}-{m.end()}, len {len(body)}) ---")
    print("  unique django tags:", sorted({t for t in tags})[:15])
    print("  total tag count:", len(tags))

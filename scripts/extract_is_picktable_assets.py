"""One-shot extractor: pull inline <style> and <script> blocks out of
``IS_PickTable.html`` into external static files while preserving exact
content (and the single ``{% static %}`` reference in the JS).

This script is idempotent only when the template still contains the
inline blocks; once extracted, re-running it will simply find no blocks
to extract and exit cleanly. Safe to keep in the repo for repeatability.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "static" / "templates" / "Input_Screening" / "IS_PickTable.html"
CSS_OUT = ROOT / "static" / "css" / "inputscreening_picktable.css"
JS_OUT = ROOT / "static" / "js" / "inputscreening_picktable.js"

DEBUG_SCRIPT_FRAGMENT = "🔥 CRITICAL DEBUG: IS_PickTable.html LOADED 🔥"
STATIC_VIEW_ICON_TAG = "{% static 'assets/icons/view2.png' %}"


def main() -> None:
    src = TEMPLATE.read_text(encoding="utf-8")

    # --- Extract the single <style> block ----------------------------------
    style_match = re.search(r"<style[^>]*>(.*?)</style>", src, re.DOTALL)
    if not style_match:
        print("No <style> block found – assuming already extracted.")
    else:
        css_body = style_match.group(1).strip("\n")
        CSS_OUT.parent.mkdir(parents=True, exist_ok=True)
        CSS_OUT.write_text(css_body + "\n", encoding="utf-8")
        print(f"Wrote CSS: {CSS_OUT} ({len(css_body)} bytes)")

    # --- Collect substantive <script> blocks (skip the tiny debug one) -----
    script_iter = list(re.finditer(r"<script[^>]*>(.*?)</script>", src, re.DOTALL))
    substantive = []
    for m in script_iter:
        body = m.group(1)
        # Skip external <script src="..."> tags (none today, defensive).
        if "src=" in m.group(0)[: m.group(0).find(">")]:
            continue
        # Skip the tiny debug log (kept inline in the template).
        if DEBUG_SCRIPT_FRAGMENT in body and len(body) < 300:
            continue
        substantive.append((m.start(), m.end(), body))

    if substantive:
        merged_parts = []
        for idx, (_s, _e, body) in enumerate(substantive, start=1):
            cleaned = body.strip("\n")
            # Replace the lone Django template tag with a JS lookup against
            # the bootstrap object exposed by the inline shim.
            cleaned = cleaned.replace(
                STATIC_VIEW_ICON_TAG,
                '${(window.IS_STATIC && window.IS_STATIC.viewIcon) || ""}',
            )
            merged_parts.append(
                f"// ====== Original inline block #{idx} ======\n{cleaned}\n"
            )
        JS_OUT.parent.mkdir(parents=True, exist_ok=True)
        JS_OUT.write_text("\n".join(merged_parts), encoding="utf-8")
        print(f"Wrote JS: {JS_OUT} (blocks={len(substantive)})")

    # --- Rewrite the template ---------------------------------------------
    new_src = src

    if style_match:
        link_tag = (
            "<link rel=\"stylesheet\" "
            "href=\"{% static 'css/inputscreening_picktable.css' %}\">"
        )
        new_src = new_src.replace(style_match.group(0), link_tag, 1)

    if substantive:
        first_block_full = src[substantive[0][0] : substantive[0][1]]
        bootstrap_and_external = (
            "<script nonce=\"{{ csp_nonce }}\">\n"
            "  window.IS_STATIC = window.IS_STATIC || {};\n"
            "  window.IS_STATIC.viewIcon = \"{% static 'assets/icons/view2.png' %}\";\n"
            "</script>\n"
            "<script nonce=\"{{ csp_nonce }}\" "
            "src=\"{% static 'js/inputscreening_picktable.js' %}\" defer></script>"
        )
        new_src = new_src.replace(first_block_full, bootstrap_and_external, 1)
        # Remove the remaining inline blocks.
        for _s, _e, body in substantive[1:]:
            full = src[_s:_e]
            new_src = new_src.replace(full, "", 1)

    TEMPLATE.write_text(new_src, encoding="utf-8")
    print(f"Rewrote template: {TEMPLATE} (new len={len(new_src)})")


if __name__ == "__main__":
    main()

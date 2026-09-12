#!/usr/bin/env python3
"""Automated palette audit (v3 §2): scan CSS/JS/HTML for unintended pink,
magenta, purple, electric-blue, and bright-cyan color literals. Hex (#rgb,
#rrggbb, 0xrrggbb) and rgb()/rgba() forms are parsed, converted to HSL, and
flagged by hue band. Allowlisted values are the documented, validated chart
series slots (data identity, CVD-checked) — nothing else.

Exit 0 = clean. Run:  python3 scripts/audit_palette.py
"""
import re
import sys
import colorsys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "dashboard"
FILES = list(ROOT.glob("*.html")) + list((ROOT / "assets").glob("*.js")) + \
        list((ROOT / "assets").glob("*.css"))

# documented exceptions: validated chart-series data colors only
ALLOW = set()

HEX = re.compile(r"(?:#|0x)([0-9a-fA-F]{6})\b|#([0-9a-fA-F]{3})\b")
RGB = re.compile(r"rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})")


def classify(r, g, b):
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    hue = h * 360
    if s < 0.22 or l < 0.09 or l > 0.97:
        return None                      # neutral / near-black / near-white
    if 285 <= hue <= 350 and s > 0.28:
        return "pink/magenta"
    if 250 <= hue < 285 and s > 0.28:
        return "purple"
    if 195 <= hue < 250 and s > 0.5 and l > 0.35:
        return "electric blue"
    if 165 <= hue < 195 and s > 0.45 and l > 0.4:
        return "bright cyan"
    return None


def main():
    hits = []
    for f in FILES:
        if "vendor" in str(f) or "acceptance" in str(f):
            continue
        text = f.read_text(errors="ignore")
        for i, line in enumerate(text.splitlines(), 1):
            vals = []
            for m in HEX.finditer(line):
                hx = m.group(1) or "".join(c * 2 for c in m.group(2))
                vals.append((hx.lower(), tuple(int(hx[j:j + 2], 16) for j in (0, 2, 4))))
            for m in RGB.finditer(line):
                r, g, b = (int(m.group(k)) for k in (1, 2, 3))
                vals.append((f"{r:02x}{g:02x}{b:02x}", (r, g, b)))
            for hx, (r, g, b) in vals:
                if hx in ALLOW:
                    continue
                verdict = classify(r, g, b)
                if verdict:
                    hits.append(f"{f.relative_to(ROOT.parent)}:{i}: #{hx} → {verdict}   | {line.strip()[:100]}")
    if hits:
        print(f"PALETTE AUDIT: {len(hits)} prohibited value(s):")
        for h in hits:
            print(" ", h)
        return 1
    print(f"PALETTE AUDIT: clean — no pink/magenta/purple/electric-blue/bright-cyan in {len(FILES)} files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

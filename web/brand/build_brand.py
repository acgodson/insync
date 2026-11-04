#!/usr/bin/env python3
"""Regenerate every InSync brand asset from one geometry definition.

Usage:  python3 web/brand/build_brand.py
Needs:  rsvg-convert, Pillow, fontTools, and Inter-SemiBold.ttf (path below or $INTER_TTF)
        for the outlined wordmark.

Geometry is measured from web/brand/team-mark-reference.jpg (primary mark, 1 unit = 1 px of
the reference at its native 1440 px width): mark box 164 x 124, finger / bar width 17.
"""
import math, os, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent

FOREST, SAGE, MOSS, INK = "#1E2B1C", "#D3DCC2", "#6F8A5C", "#111111"
BLUE, AMBER, PAPER = "#8EC5E8", "#E9B84E", "#F3F3EE"

W = 17          # bar / finger / thumb width
R = W / 2

def rect(x, y, w, h, rx):
    return f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="{rx:g}"/>'

def bars():
    return rect(0, 50, W, 27, R) + rect(22, 37, W, 52, R)

def hand():
    # four fingers (x 44..127, 5 px gaps, middle finger tallest) fused into a palm with
    # rounded lower corners, as one path so there are no seams.
    fingers = [(44, 25), (66, 9), (88, 0), (110, 9)]
    top_palm, bottom, pr = 66, 124, 20
    d = []
    x0 = 44
    d.append(f"M{x0} {bottom - pr}")
    for i, (fx, fy) in enumerate(fingers):
        d.append(f"L{fx} {fy + R}")
        d.append(f"A{R} {R} 0 0 1 {fx + W} {fy + R}")
        if i < len(fingers) - 1:
            nx = fingers[i + 1][0]
            d.append(f"L{fx + W} {top_palm}")
            d.append(f"L{nx} {top_palm}")
    d.append(f"L127 {bottom - pr}")
    d.append(f"A{pr} {pr} 0 0 1 {127 - pr} {bottom}")
    d.append(f"L{x0 + pr} {bottom}")
    d.append(f"A{pr} {pr} 0 0 1 {x0} {bottom - pr}Z")
    return f'<path d="{" ".join(d)}"/>'

def thumb():
    # capsule between centres (137.5,103.5) and (155.5,77.5)
    (x1, y1), (x2, y2) = (137.5, 103.5), (155.5, 77.5)
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    ang = math.degrees(math.atan2(y2 - y1, x2 - x1))
    L = math.hypot(x2 - x1, y2 - y1) + W
    return (f'<rect x="{cx - L/2:.2f}" y="{cy - R:g}" width="{L:.2f}" height="{W}" rx="{R}" '
            f'transform="rotate({ang:.2f} {cx:g} {cy:g})"/>')

def mark_group(bar_c, hand_c, thumb_c, tx=0, ty=0, s=1):
    t = f' transform="translate({tx:g} {ty:g}) scale({s:g})"' if (tx or ty or s != 1) else ""
    return (f'<g{t}><g fill="{bar_c}">{bars()}</g><g fill="{hand_c}">{hand()}</g>'
            f'<g fill="{thumb_c}">{thumb()}</g></g>')

def svg(vb, body, title="InSync"):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}" role="img" aria-label="{title}">'
            f'<title>{title}</title>{body}</svg>\n')

# Mark sits in 0..164 x 0..124; centre (82,62).
MARK_VB = "-8 -28 180 180"

# ---- wordmark ---------------------------------------------------------------------------------
FONT_SIZE = 113.5          # x-height = 0.5 * mark height, as in the reference lockup
TEXT_X, BASELINE = 206, 99.2
TARGET_W = 325.5           # measured ink width of "insync" in the reference, in mark units
WORD = "insync"
FONT_STACK = "Inter, 'Atkinson Hyperlegible', system-ui, -apple-system, 'Segoe UI', sans-serif"

def find_inter():
    cands = [os.environ.get("INTER_TTF", ""),
             str(HERE / "fonts/Inter-SemiBold.ttf"),
             "/Users/godson/Desktop/atelo-hub/apps/mobile/assets/fonts/inter/Inter-SemiBold.ttf"]
    return next((c for c in cands if c and Path(c).exists()), None)

def wordmark_paths(fill):
    """Return (svg_group, tracking_px) for "insync" in Inter SemiBold, outlined."""
    from fontTools.ttLib import TTFont
    from fontTools.pens.svgPathPen import SVGPathPen
    from fontTools.pens.boundsPen import BoundsPen
    f = TTFont(find_inter())
    gs, cmap, upm = f.getGlyphSet(), f.getBestCmap(), f["head"].unitsPerEm
    sc = FONT_SIZE / upm
    names = [cmap[ord(c)] for c in WORD]
    adv = [f["hmtx"][n][0] for n in names]
    # ink width without tracking
    def ink(track_units):
        x, lo, hi = 0, None, None
        for n, a in zip(names, adv):
            bp = BoundsPen(gs); gs[n].draw(bp)
            if bp.bounds:
                lo = x + bp.bounds[0] if lo is None else lo
                hi = x + bp.bounds[2]
            x += a + track_units
        return hi - lo, lo
    w0, lo = ink(0)
    track = (TARGET_W / sc - w0) / (len(WORD) - 1)
    parts, x = [], -lo
    for n, a in zip(names, adv):
        pen = SVGPathPen(gs, lambda v: f"{v:.1f}".rstrip("0").rstrip("."))
        gs[n].draw(pen)
        parts.append(f'<path transform="translate({x:.1f} 0)" d="{pen.getCommands()}"/>')
        x += a + track
    g = (f'<g fill="{fill}" transform="translate({TEXT_X} {BASELINE}) scale({sc:.5f} {-sc:.5f})">'
         + "".join(parts) + "</g>")
    return g, track * sc

def main():
    out = {}
    out["insync-mark.svg"] = svg(MARK_VB, mark_group(BLUE, PAPER, AMBER))
    out["insync-mark-light.svg"] = svg(MARK_VB, mark_group(MOSS, FOREST, AMBER))
    out["insync-mark-mono-white.svg"] = svg(MARK_VB, mark_group(PAPER, PAPER, PAPER))

    word_dark, track_px = wordmark_paths(PAPER)
    word_light, _ = wordmark_paths(FOREST)
    LOCK_VB = "-4 -4 540 132"
    out["insync-lockup.svg"] = svg(LOCK_VB, mark_group(BLUE, PAPER, AMBER) +
        f'<text x="{TEXT_X}" y="{BASELINE}" fill="{PAPER}" font-family="{FONT_STACK}" '
        f'font-weight="600" font-size="{FONT_SIZE}" letter-spacing="{track_px:.2f}">{WORD}</text>')
    out["insync-lockup-outlined.svg"] = svg(LOCK_VB, mark_group(BLUE, PAPER, AMBER) + word_dark)
    out["insync-lockup-light.svg"] = svg(LOCK_VB, mark_group(MOSS, FOREST, AMBER) + word_light)

    # favicon: ink rounded square, reversed mark at ~78 % width
    s = 0.78 * 100 / 164
    out["favicon.svg"] = svg("0 0 100 100", f'<rect width="100" height="100" rx="22" fill="{INK}"/>' +
        mark_group(BLUE, PAPER, AMBER, 50 - 82 * s, 50 - 62 * s, s))
    # app icon: ink rounded square, all-white mark (as the reference app icon)
    s = 0.64 * 1024 / 164
    out["icon.svg"] = svg("0 0 1024 1024", f'<rect width="1024" height="1024" rx="230" fill="{INK}"/>' +
        mark_group(PAPER, PAPER, PAPER, 512 - 82 * s, 512 - 62 * s, s))

    for name, text in out.items():
        (HERE / name).write_text(text)
        print("wrote", HERE / name)

    def render(src, dst, w, h=None):
        dst.parent.mkdir(parents=True, exist_ok=True)
        cmd = ["rsvg-convert", "-w", str(w)] + (["-h", str(h)] if h else []) + ["-o", str(dst), str(src)]
        subprocess.run(cmd, check=True); print("wrote", dst)

    render(HERE / "favicon.svg", HERE / "favicon-32.png", 32)
    render(HERE / "icon.svg", HERE / "icon-1024.png", 1024)
    render(HERE / "insync-mark.svg", ROOT / "app/assets/brand/insync-mark.png", 512)

    from PIL import Image
    icon = Image.open(HERE / "icon-1024.png").convert("RGBA")
    res = ROOT / "app/android/app/src/main/res"
    for d, px in [("mdpi", 48), ("hdpi", 72), ("xhdpi", 96), ("xxhdpi", 144), ("xxxhdpi", 192)]:
        p = res / f"mipmap-{d}/ic_launcher.png"
        icon.resize((px, px), Image.LANCZOS).save(p, optimize=True); print("wrote", p)

if __name__ == "__main__":
    main()

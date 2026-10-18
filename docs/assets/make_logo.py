"""Draw Gamut's logo (logo.svg, and logo-dark.svg for dark pages) and mark (mark.svg).

The mark is two sheets of one mesh, one behind the other: every run of a
study lies on the same mesh, so a study is a stack of the same meshed sheet.
The front sheet is in TopoLink's blue and the sheet behind in Bijective
Systems' light blue; the one behind stops short of the front so the two stay
apart on light and dark pages alike. The name is set like BIJECTIVE in the
company's wordmark: a capital G, then AMUT in small capitals, in Inter
Display (SIL Open Font License), drawn as outlines so no font is needed.

Usage: python docs/assets/make_logo.py INTER_TTF_DIR
  (the extras/ttf folder of an Inter release, https://github.com/rsms/inter;
  needs fontTools)
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

HERE = Path(__file__).resolve().parent
FRONT, BACK = "#0070DC", "#74BFF8"
INK, INK_DARK = "#1F2328", "#E6EDF3"
STROKE, GAP = 3.4, 2.6        # line width, and the clearance around the front sheet
STEPS = 48                    # points along each wavy edge


def sheet(ox: float, oy: float) -> tuple[str, str, list[tuple[float, float]]]:
    """One sheet: its outline, its mesh lines, and its outline's points."""
    def top(u: float) -> tuple[float, float]:
        return ox + 30 * u, oy - 12 * u + 5 * math.sin(2 * math.pi * u)
    across = (7.0, 13.0)
    def bottom(u: float) -> tuple[float, float]:
        x, y = top(u)
        return x + across[0], y + across[1]
    us = [k / STEPS for k in range(STEPS + 1)]
    pts = [top(u) for u in us] + [bottom(u) for u in reversed(us)]
    mid = [(top(u)[0] + across[0] / 2, top(u)[1] + across[1] / 2) for u in us]
    mesh = " ".join(line([top(u), bottom(u)]) for u in (1 / 3, 2 / 3)) + " " + line(mid)
    return line(pts) + "Z", mesh, pts


def line(pts: list[tuple[float, float]]) -> str:
    return "M" + "L".join(f"{x:.2f} {y:.2f}" for x, y in pts)


def mark(size: float, prefix: str) -> str:
    """The mark scaled into a size x size square at the origin."""
    front, front_mesh, fp = sheet(0, 0)
    back, back_mesh, bp = sheet(6, -16)
    xs, ys = [p[0] for p in fp + bp], [p[1] for p in fp + bp]
    pad = STROKE  # half a line for the round ends, and a margin as wide again
    w, h = max(xs) - min(xs) + 2 * pad, max(ys) - min(ys) + 2 * pad
    s = size / max(w, h)
    tx = -min(xs) + pad + (max(w, h) - w) / 2
    ty = -min(ys) + pad + (max(w, h) - h) / 2
    return (f'<g transform="scale({s:.4f}) translate({tx:.3f} {ty:.3f})" fill="none" '
            f'stroke-width="{STROKE}" stroke-linecap="round" stroke-linejoin="round">'
            f'<mask id="{prefix}-clear" maskUnits="userSpaceOnUse" x="-50" y="-50" width="150" height="150">'
            f'<rect x="-50" y="-50" width="150" height="150" fill="white"/>'
            f'<path d="{front}" fill="black" stroke="black" stroke-width="{STROKE + 2 * GAP}"/></mask>'
            f'<g mask="url(#{prefix}-clear)" stroke="{BACK}"><path d="{back}"/><path d="{back_mesh}"/></g>'
            f'<g stroke="{FRONT}"><path d="{front}"/><path d="{front_mesh}"/></g></g>')


def outlines(text: str, font: TTFont, size: float, x: float, baseline: float,
             tracking: float = 0.0) -> tuple[str, float]:
    glyphs, cmap, metrics = font.getGlyphSet(), font.getBestCmap(), font["hmtx"]
    scale = size / font["head"].unitsPerEm
    pen = SVGPathPen(glyphs)
    advance = 0.0
    for ch in text:
        name = cmap[ord(ch)]
        glyphs[name].draw(TransformPen(pen, (scale, 0, 0, -scale, x + advance * scale, baseline)))
        advance += metrics[name][0] + tracking * font["head"].unitsPerEm
    return pen.getCommands(), advance * scale


def main(inter: Path) -> int:
    bold = TTFont(inter / "InterDisplay-Bold.ttf")
    heavy = TTFont(inter / "InterDisplay-ExtraBold.ttf")
    x0, baseline, size = 62.0, 46.0, 54.0
    g, g_width = outlines("G", bold, 46, x0, baseline)
    # The small capitals a step heavier, so their strokes match the G's.
    rest, rest_width = outlines("AMUT", heavy, 36, x0 + g_width + 0.5, baseline, tracking=0.01)
    width = math.ceil(x0 + g_width + 0.5 + rest_width + 2)
    note = "<!-- Drawn by make_logo.py; see its docstring for what the mark means. -->"
    # Two fixed colourings rather than one that follows the system's colour scheme:
    # GitHub's theme can differ from the system's, and the README's <picture> follows
    # GitHub's.
    for name, ink in (("logo.svg", INK), ("logo-dark.svg", INK_DARK)):
        (HERE / name).write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {size:g}" '
            f'width="{width}" height="{size:g}" role="img" aria-labelledby="gamut-logo">\n'
            f'  <title id="gamut-logo">Gamut</title>\n  {note}\n'
            f'  {mark(size, "gamut-logo")}\n  <path fill="{ink}" d="{g} {rest}"/>\n</svg>\n')
    (HERE / "mark.svg").write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size:g} {size:g}" '
        f'width="{size:g}" height="{size:g}" role="img" aria-labelledby="gamut-mark">\n'
        f'  <title id="gamut-mark">Gamut</title>\n  {note}\n  {mark(size, "gamut-mark")}\n</svg>\n')
    print(f"wrote logo.svg and logo-dark.svg ({width} x {size:g}) and mark.svg in {HERE}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    raise SystemExit(main(Path(sys.argv[1])))

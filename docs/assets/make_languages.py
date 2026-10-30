"""Draws docs/assets/languages.svg and languages-dark.svg: every language
reads and writes a .gamut file through the one C++ core.

    python docs/assets/make_languages.py

The core exports its C interface only, so every language, C++ included
(gamut.hpp is a header over gamut.h), reaches it through that interface:
the strip on the core's edge that each two-way arrow enters. The command
line is the Python package's. Planned languages are greyed and dashed. The
file is the Gamut mark (mark.svg, drawn by make_logo.py). The colours and
type are those of the README's other figures.
"""
from __future__ import annotations

import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
THEMES = {
    "light": dict(page="#FFFFFF", ink="#1F2328", soft="#59636E", faint="#8C959F", rule="#D0D7DE",
                  band="#EEF6FE", edge="#74BFF8", arrow="#0070DC"),
    "dark": dict(page="#0D1117", ink="#E6EDF3", soft="#9198A1", faint="#6E7681", rule="#30363D",
                 band="#11243A", edge="#0B4FA8", arrow="#4A9FF5"),
}
FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
LANGUAGES = [("Python", True), ("MATLAB", True), ("Julia", True), ("C++", True), ("C", True),
             ("Rust", True), ("Fortran", False)]
STRIP = 30                                            # the C interface, on the core's edge
W, M = 760, 10
BOX_W, BOX_H, GAP = 156, 34, 10                       # a language
CORE_X, CORE_W = 286, 176                             # the core
FILE_X = 600                                          # the file's left edge
H = 2 * M + len(LANGUAGES) * BOX_H + (len(LANGUAGES) - 1) * GAP


def text(x, y, s, fill, size=15, weight=400, anchor="middle", family=FONT, style=""):
    return (f'<text x="{x:.1f}" y="{y:.1f}" fill="{fill}" font-family="{family}" font-size="{size}" '
            f'font-weight="{weight}" text-anchor="{anchor}"{style}>{s}</text>')


def arrow(x0, x1, y, colour, dashed=False):
    """A two-way arrow from x0 to x1 at height y."""
    head = 6
    dash = ' stroke-dasharray="4 4"' if dashed else ""
    return (f'<line x1="{x0 + head:.1f}" y1="{y:.1f}" x2="{x1 - head:.1f}" y2="{y:.1f}" stroke="{colour}" '
            f'stroke-width="1.6"{dash}/>'
            f'<path d="M{x0:.1f} {y:.1f}l{head + 2} {-head + 1.5}v{2 * head - 3}z" fill="{colour}"/>'
            f'<path d="M{x1:.1f} {y:.1f}l{-head - 2} {-head + 1.5}v{2 * head - 3}z" fill="{colour}"/>')


def mark(x, y, size):
    """The Gamut mark, as drawn by make_logo.py, at (x, y) and size wide."""
    with open(os.path.join(HERE, "mark.svg"), encoding="utf-8") as f:
        svg = f.read()
    inner = re.search(r"<svg[^>]*>(.*)</svg>", svg, re.S).group(1)
    inner = re.sub(r"<title[^>]*>.*?</title>|<!--.*?-->", "", inner, flags=re.S)
    return f'<svg x="{x:.1f}" y="{y:.1f}" width="{size}" height="{size}" viewBox="0 0 54 54">{inner}</svg>'


def draw(c: dict) -> str:
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
         f'role="img" aria-labelledby="languages-title">',
         '<title id="languages-title">Python (with the command line), MATLAB, Julia, C++, C and Rust each '
         'read and write a .gamut file through the C interface of the one C++ core; Fortran is '
         'planned.</title>',
         f'<rect width="{W}" height="{H}" fill="{c["page"]}"/>']
    core_y, core_h = M, H - 2 * M
    for i, (name, ready) in enumerate(LANGUAGES):
        y = M + i * (BOX_H + GAP)
        mid = y + BOX_H / 2
        if ready:
            o.append(f'<rect x="{M}" y="{y}" width="{BOX_W}" height="{BOX_H}" rx="6" fill="{c["page"]}" '
                     f'stroke="{c["rule"]}" stroke-width="1.5"/>')
            if name == "Python":                      # the command line is the Python package's
                o.append(f'<text x="{M + BOX_W / 2:.1f}" y="{mid + 5:.1f}" font-family="{FONT}" '
                         f'font-size="15" text-anchor="middle"><tspan fill="{c["ink"]}">Python</tspan>'
                         f'<tspan fill="{c["soft"]}"> · CLI</tspan></text>')
            else:
                o.append(text(M + BOX_W / 2, mid + 5, name, c["ink"]))
            o.append(arrow(M + BOX_W + 8, CORE_X - 8, mid, c["arrow"]))
        else:
            o.append(f'<rect x="{M}" y="{y}" width="{BOX_W}" height="{BOX_H}" rx="6" fill="{c["page"]}" '
                     f'stroke="{c["rule"]}" stroke-width="1.5" stroke-dasharray="4 3"/>')
            o.append(text(M + 16, mid + 5, name, c["faint"], anchor="start"))
            o.append(text(M + BOX_W - 14, mid + 4, "planned", c["faint"], size=12, anchor="end",
                          style=' font-style="italic"'))
            o.append(arrow(M + BOX_W + 8, CORE_X - 8, mid, c["rule"], dashed=True))
    # The core: one library behind one C interface.
    o.append(f'<rect x="{CORE_X}" y="{core_y}" width="{CORE_W}" height="{core_h}" rx="8" fill="{c["band"]}" '
             f'stroke="{c["edge"]}" stroke-width="1.5"/>')
    # The C interface: a strip on the edge every language enters by.
    o.append(f'<path d="M{CORE_X + STRIP} {core_y}v{core_h}" stroke="{c["edge"]}" stroke-width="1.5"/>')
    o.append(f'<text transform="translate({CORE_X + STRIP / 2 + 4.5:.1f} {H / 2:.1f}) rotate(-90)" '
             f'fill="{c["soft"]}" font-family="{MONO}" font-size="12.5" text-anchor="middle">'
             f'C interface · gamut.h</text>')
    centre = CORE_X + STRIP + (CORE_W - STRIP) / 2
    o.append(text(centre, H / 2 - 4, "C++ core", c["ink"], size=18, weight=600))
    o.append(text(centre, H / 2 + 18, "libgamut", c["soft"], size=12.5, family=MONO))
    # The file, reached only through the core.
    o.append(arrow(CORE_X + CORE_W + 8, FILE_X - 8, H / 2, c["arrow"]))
    o.append(text((CORE_X + CORE_W + FILE_X) / 2, H / 2 - 12, "read · write", c["soft"], size=12.5))
    box_w, box_h = W - M - FILE_X, 168
    top = H / 2 - box_h / 2
    o.append(f'<rect x="{FILE_X}" y="{top:.1f}" width="{box_w}" height="{box_h}" rx="8" fill="{c["page"]}" '
             f'stroke="{c["edge"]}" stroke-width="1.5"/>')
    size = 76
    fx = FILE_X + (box_w - size) / 2
    o.append(mark(fx, top + 16, size))
    o.append(text(FILE_X + box_w / 2, top + 16 + size + 26, ".gamut file", c["ink"], size=15, weight=600))
    o.append(text(FILE_X + box_w / 2, top + 16 + size + 46, "HDF5 as netCDF-4", c["soft"], size=12.5))
    o.append("</svg>")
    return "\n".join(o) + "\n"


if __name__ == "__main__":
    for theme, name in (("light", "languages.svg"), ("dark", "languages-dark.svg")):
        with open(os.path.join(HERE, name), "w", encoding="utf-8") as f:
            f.write(draw(THEMES[theme]))
    print(f"wrote languages.svg and languages-dark.svg ({W} x {H}) in {HERE}")

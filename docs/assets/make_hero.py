"""Draws docs/assets/hero.svg and hero-dark.svg, the README's picture: one
study file laid open.

    python docs/assets/make_hero.py NACA4412.gamut

NACA4412.gamut is the XFOIL sweep that docs/assets/hero_sweep.py runs and
writes. Each drawn run is one row of the file's table: its inputs, status,
split and results with units, the transition spread stored beside cl, and
then its pressure coefficient at every node of the mesh all runs share. A
selection shades the runs it picks. Every name, unit and value is read from
the file with gamut.
"""
from __future__ import annotations

import base64
import io
import os
import sys

import numpy as np
from matplotlib.colors import LinearSegmentedColormap, to_hex
from PIL import Image

import gamut

HERE = os.path.dirname(os.path.abspath(__file__))
QUERY = "reynolds == 1e6 and alpha > 10"
SHOWN = [0, None, 85, None, 202, 203, None, 241, None, 362]   # rows drawn; None stands for rows not drawn
LO, HI = -6.0, 1.0                                          # colour scale for cp; below LO shows as LO
THEMES = {
    "light": dict(page="#FFFFFF", ink="#1F2328", soft="#59636E", faint="#8C959F", rule="#D0D7DE",
                  code="#0A3069", band="#EEF6FE", mark="#0070DC",
                  ramp=["#08224F", "#0B4FA8", "#0070DC", "#74BFF8", "#D9EEFD", "#FFFFFF"]),
    "dark": dict(page="#0D1117", ink="#E6EDF3", soft="#9198A1", faint="#6E7681", rule="#30363D",
                 code="#A5D6FF", band="#11243A", mark="#4A9FF5",
                 ramp=["#E3F2FE", "#74BFF8", "#0070DC", "#0B4FA8", "#0B2550", "#0D1117"]),
}
FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
W, M = 760, 10


def num(v: float, fmt: str = "g") -> str:
    """A number as set in text, with a true minus sign."""
    return format(v, fmt).replace("-", "−")


def sci(v: float) -> str:
    """2e5 as 2·10⁵."""
    exp = int(np.floor(np.log10(v)))
    mant = v / 10 ** exp
    sup = str(exp).translate(str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹"))
    return f"10{sup}" if mant == 1 else f"{mant:g}·10{sup}"


def read(path: str) -> dict:
    shown = [r for r in SHOWN if r is not None]
    with gamut.open(path) as study:
        std = study.related("cl")["std"]                    # the statistic stored beside cl
        return dict(
            n_runs=study.row_count,
            points=study.get_points(),
            units={n: study.describe(n)["units"] for n in ("alpha", "reynolds", "cl", "cd", "cm", "cp")},
            table=study.table(names=["alpha", "reynolds", "status", "split", "cl", std, "cd", "cm"], rows=shown),
            std=std,
            cp=study.get_field("cp", rows=shown),
            rows=study.select(QUERY))


def draw(d: dict, theme: str) -> str:
    c = THEMES[theme]
    ramp = LinearSegmentedColormap.from_list(theme, c["ramp"])
    o: list[str] = []

    def text(x, y, s, colour="soft", size=12, anchor="start", mono=False):
        o.append(f'<text x="{x:.1f}" y="{y:.1f}" fill="{c[colour]}" font-family="{MONO if mono else FONT}" '
                 f'font-size="{size}" text-anchor="{anchor}" style="font-variant-numeric: tabular-nums">{s}</text>')

    def strip(values, x, y, w, h):
        """Values as a palette PNG, one pixel per node; missing values transparent."""
        steps = 254
        t = np.clip((np.nan_to_num(values, nan=HI) - LO) / (HI - LO), 0.0, 1.0)
        index = np.repeat(np.round(t * (steps - 1)).astype(np.uint8)[None], int(h), 0)
        index[:, np.isnan(values)] = steps
        img = Image.fromarray(index, "P")
        rgb = (ramp(np.linspace(0, 1, steps))[:, :3] * 255).round().astype(np.uint8)
        img.putpalette(np.vstack([rgb, [[0, 0, 0]]]).ravel().tolist())
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True, transparency=steps)
        uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
        o.append(f'<image href="{uri}" x="{x}" y="{y:.1f}" width="{w}" height="{h}" preserveAspectRatio="none"/>')
        o.append(f'<rect x="{x}" y="{y:.1f}" width="{w}" height="{h}" fill="none" stroke="{c["rule"]}" '
                 f'stroke-width="0.75"/>')

    n_nodes = len(d["points"])
    t = d["table"]
    selected = set(int(r) for r in d["rows"])

    text(M, 24, "naca4412.gamut", "ink", 15, mono=True)
    text(M, 46, "One shared mesh. Each run is a row: inputs, status, split, results and a spread stored beside "
                "lift, then its field at every node.", "soft", 12.5)

    # The mesh, top right.
    aw, my = 190, 86
    sc = aw / np.ptp(d["points"][:, 0])
    pts = " ".join(f"{W - M - aw + sc * x:.1f},{my - sc * y:.1f}" for x, y in d["points"])
    o.append(f'<polyline fill="none" stroke="{c["soft"]}" stroke-width="1" stroke-linejoin="round" points="{pts}"/>')
    text(W - M - aw - 12, my + 4, f"the mesh: {n_nodes} nodes", "soft", 11.5, "end")

    # The selection.
    top = 132
    o.append(f'<text x="{M}" y="{top}" fill="{c["ink"]}" font-family="{MONO}" font-size="12">study.select('
             f'<tspan fill="{c["code"]}">"{QUERY}"</tspan>)</text>')
    text(M + 7.3 * len(f'study.select("{QUERY}")') + 14, top, f"# {len(d['rows'])} runs, shaded", "soft", 12,
         mono=True)

    # The table, each row continued by that run's cp at every node; units under the names.
    cols = [("run", None, 30, "end"), ("alpha", "alpha", 74, "end"), ("reynolds", "reynolds", 140, "end"),
            ("status", None, 152, "start"), ("split", None, 226, "start"), ("cl", "cl", 304, "end"),
            (d["std"], "cl", 360, "end"), ("cd", "cd", 414, "end"), ("cm", "cm", 462, "end")]
    fx = 480
    fw = W - M - fx
    hy, rh = top + 30, 20
    for name, unit, x, anchor in cols:
        text(x, hy, name, "ink", 12, anchor, mono=True)
        if unit:
            text(x, hy + 15, d["units"][unit], "soft", 11, anchor)
    text(fx, hy, "cp", "ink", 12, mono=True)
    text(fx + 20, hy, f"[{d['units']['cp']}] at nodes 0 to {n_nodes - 1}", "soft", 11)
    o.append('<defs><linearGradient id="cp">' + "".join(
        f'<stop offset="{s:.2f}" stop-color="{to_hex(ramp(s))}"/>' for s in np.linspace(0, 1, 11)) +
        '</linearGradient></defs>')
    text(fx + 40, hy + 15, f"≤ {num(LO)}", "soft", 11, "end")
    o.append(f'<rect x="{fx + 46}" y="{hy + 7}" width="80" height="8" fill="url(#cp)"/>')
    text(fx + 131, hy + 15, num(HI), "soft", 11)
    y0 = hy + 24
    o.append(f'<line x1="{M}" x2="{W - M}" y1="{y0}" y2="{y0}" stroke="{c["rule"]}"/>')
    k = 0
    for i, r in enumerate(SHOWN):
        y = y0 + 2 + i * rh
        inside = r in selected if r is not None else (SHOWN[i - 1] in selected and SHOWN[i + 1] in selected)
        if inside:
            o.append(f'<rect x="{M}" y="{y}" width="{W - 2 * M}" height="{rh}" fill="{c["band"]}"/>'
                     f'<rect x="2" y="{y}" width="3" height="{rh}" fill="{c["mark"]}"/>')
        if r is None:
            for x in (cols[0][2] - 4, fx + fw / 2):
                o.append("".join(f'<circle cx="{x:.1f}" cy="{y + rh / 2 + dy:.1f}" r="1" fill="{c["soft"]}"/>'
                                 for dy in (-4, 0, 4)))
            continue
        failed = t["status"][k] != "converged"
        cells = [str(r), num(t["alpha"][k], ".1f"), sci(t["reynolds"][k]), t["status"][k], t["split"][k]]
        cells += ["—"] * 4 if failed else [num(t["cl"][k], ".3f"), f"{t[d['std']][k]:.3f}",
                                             num(t["cd"][k], ".4f"), num(t["cm"][k], ".3f")]
        for (name, _, x, anchor), v in zip(cols, cells):
            soft = name == d["std"] or (failed and name in ("cl", "cd", "cm"))
            text(x, y + 14, v, "soft" if soft else "ink", 12, anchor)
        if failed:
            o.append(f'<rect x="{fx}" y="{y + 3}" width="{fw}" height="{rh - 6}" fill="none" stroke="{c["faint"]}" '
                     f'stroke-dasharray="3 3"/>')
            text(fx + fw / 2, y + 14, "no values: the run did not converge", "soft", 11, "middle")
        else:
            strip(d["cp"][k], fx, y + 3, fw, rh - 6)
        k += 1
    yb = y0 + 2 + len(SHOWN) * rh
    o.append(f'<line x1="{M}" x2="{W - M}" y1="{yb + 2}" y2="{yb + 2}" stroke="{c["rule"]}"/>')
    text(M, yb + 22, f"{d['std']}: sample standard deviation of cl over transition criteria Ncrit 7, 9 and 11 "
                     "(cl is Ncrit 9); a sensitivity, not a confidence interval.", "soft", 11.5)
    text(M, yb + 40, "split: a seeded draw of about a fifth of the runs, for testing within this sweep. "
                     "Dotted gaps stand for rows not drawn.", "soft", 11.5)
    H = yb + 72
    text(M, H - 10, f"{d['n_runs']} runs × {n_nodes} nodes in one file, read and written from Python, MATLAB, "
                    "Julia, C++ and C.", "soft", 11.5)
    text(W - M, H - 10, "Data: XFOIL 6.99, NACA 4412", "soft", 11.5, "end")
    head = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" '
            f'aria-label="A Gamut study file laid open: each run one table row with its inputs, status, split, '
            f'results and the spread of its lift over transition criteria, continued by its pressure coefficient at every node of '
            f'the shared mesh, with a query shading the runs it picks." xml:space="preserve">'
            f'<rect width="100%" height="100%" fill="{c["page"]}"/>')
    return head + "\n" + "\n".join(o) + "\n</svg>\n"


def main(path: str) -> None:
    data = read(path)
    for theme, name in (("light", "hero.svg"), ("dark", "hero-dark.svg")):
        with open(os.path.join(HERE, name), "w", encoding="utf-8") as fh:
            fh.write(draw(data, theme))


if __name__ == "__main__":
    main(sys.argv[1])

"""Draws docs/assets/hero.svg, the README's picture: a query and what it returns.

    python docs/assets/make_hero.py AIRFRANS.gamut

AIRFRANS.gamut is the 100-run subset of AirfRANS (Bonnet et al., NeurIPS
2022; ODbL) that bench/airfrans.py fetches, turned into one file by
`gamut-vtk import`. The picture is one select call, the rows it returns
with their stored names and units, and for each row the pressure field
gamut reads for that run, rendered with PyVista.
"""

from __future__ import annotations

import base64
import io
import os
import sys

import numpy as np
import pyvista as pv
from PIL import Image

import gamut

HERE = os.path.dirname(os.path.abspath(__file__))
QUERY = "angle_of_attack > 14"
SCALE = (-3.0, 1.0)           # p / (0.5 inflow_speed^2)
VIEW = (0.55, 0.0, 0.30)      # centre x, centre y and half height, in chords
STYLE = """<style>
    .ink { fill: #1F2328; } .soft { fill: #59636E; } .rule { stroke: #D0D7DE; } .str { fill: #0A3069; }
    .page { fill: #FFFFFF; }
    @media (prefers-color-scheme: dark) {
      .page { fill: #0D1117; } .ink { fill: #E6EDF3; } .soft { fill: #9198A1; } .rule { stroke: #30363D; }
      .str { fill: #A5D6FF; }
    }
    text { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; font-size: 12px; }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
    .num { font-variant-numeric: tabular-nums; }
    .h { font-weight: 600; }
  </style>"""


def colour(v: np.ndarray) -> np.ndarray:
    """RdBu_r split at 0: blue from SCALE[0] up to 0, red from 0 up to SCALE[1]."""
    import matplotlib
    lo, hi = SCALE
    v = np.asarray(v, dtype=float)
    position = np.where(v < 0, 0.5 * (v - lo) / -lo, 0.5 + 0.5 * v / hi)
    return matplotlib.colormaps["RdBu_r"](np.clip(position, 0.0, 1.0))


def colour_map():
    from matplotlib.colors import ListedColormap
    return ListedColormap(colour(np.linspace(SCALE[0], SCALE[1], 512)))


def render(study, row: int, width: int, height: int) -> str:
    """One run's pressure, over half the inflow speed squared, near the
    airfoil, as a JPEG data URI."""
    points = study.get_points(row=row)
    types, offsets, connectivity = study.get_cells(row=row)
    cells = np.insert(connectivity, offsets[:-1], np.diff(offsets))
    xyz = points if points.shape[1] == 3 else np.c_[points, np.zeros(len(points))]
    grid = pv.UnstructuredGrid(cells, types, xyz)
    inflow = float(study.get_parameter("inflow_speed", rows=[row])[0])
    grid.point_data["cp"] = study.get_field("p", rows=[row]).ravel() / (0.5 * inflow ** 2)
    plotter = pv.Plotter(off_screen=True, window_size=(width, height))
    plotter.add_mesh(grid, scalars="cp", cmap=colour_map(), clim=SCALE, lighting=False, show_scalar_bar=False)
    x, y, half = VIEW
    plotter.camera.position = (x, y, 5.0)
    plotter.camera.focal_point = (x, y, 0.0)
    plotter.camera.up = (0.0, 1.0, 0.0)
    plotter.enable_parallel_projection()
    plotter.camera.parallel_scale = half
    image = Image.fromarray(plotter.screenshot(return_img=True))
    plotter.close()
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=88, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()


def main(path: str) -> None:
    import matplotlib
    width, top, thumb_w = 760, 64, 250
    thumb_h = round(thumb_w / 2.3)             # the view: 1.38 chords by 0.6
    row_h = thumb_h + 12
    columns = [("run", None, 0, "start"), ("angle_of_attack", "degree", 182, "end"),
               ("inflow_speed", "m s-1", 300, "end"), ("naca_t", "1", 372, "end"), ("split", None, 400, "start")]
    field_x = width - thumb_w
    with gamut.open(path) as study:
        rows = [int(r) for r in study.select(QUERY)]
        total = study.row_count
        table = []
        for row in rows:
            values = [f"{int(study.get_row_ids(rows=[row])[0])}"]
            for name, units, _, _ in columns[1:4]:
                values.append(f"{float(study.get_parameter(name, rows=[row])[0]):.2f}")
            values.append(str(study.get_label("split", rows=[row])[0]))
            table.append((values, render(study, row, 2 * thumb_w, 2 * thumb_h)))
    height = top + 40 + row_h * len(table) + 40
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" '
           f'height="{height}" role="img" aria-label="A query on a study file and the rows it returns, each '
           f'with its values and the pressure field read for that run">', STYLE,
           '<rect class="page" width="100%" height="100%"/>',
           f'<text class="ink mono" x="0" y="20">rows = study.select(<tspan class="str">"{QUERY}"</tspan>)'
           f'</text>',
           f'<text class="soft mono" x="0" y="42"># {len(rows)} of {total} runs in {os.path.basename(path)}</text>']
    y = top + 14
    for name, units, x, anchor in columns:
        out.append(f'<text class="ink mono" x="{x}" y="{y}" text-anchor="{anchor}">{name}</text>')
        if units:
            out.append(f'<text class="soft" x="{x}" y="{y + 16}" text-anchor="{anchor}">{units}</text>')
    out.append(f'<text class="ink mono" x="{field_x}" y="{y}">study.get_field("p", rows=r)</text>')
    out.append(f'<text class="soft" x="{field_x}" y="{y + 16}">divided by 0.5 · inflow_speed²</text>')
    out.append(f'<line class="rule" x1="0" y1="{y + 26}" x2="{width}" y2="{y + 26}"/>')
    for k, (values, image) in enumerate(table):
        y0 = top + 40 + k * row_h
        mid = y0 + row_h / 2 + 4
        for (name, _, x, anchor), text in zip(columns, values):
            cls = "ink mono" if name in ("run", "split") else "ink num"
            out.append(f'<text class="{cls}" x="{x}" y="{mid:.0f}" text-anchor="{anchor}">{text}</text>')
        out.append(f'<image href="{image}" x="{field_x}" y="{y0 + 6}" width="{thumb_w}" height="{thumb_h}"/>')
    bar_y = top + 40 + row_h * len(table) + 14
    values = np.linspace(SCALE[0], SCALE[1], 17)
    stops = "".join(f'<stop offset="{(v - SCALE[0]) / (SCALE[1] - SCALE[0]):.3f}" '
                    f'stop-color="{matplotlib.colors.to_hex(c)}"/>' for v, c in zip(values, colour(values)))
    out += [f'<defs><linearGradient id="cp">{stops}</linearGradient></defs>',
            f'<rect x="{field_x}" y="{bar_y}" width="{thumb_w}" height="8" fill="url(#cp)"/>',
            f'<text class="soft" x="{field_x}" y="{bar_y + 22}">≤ {SCALE[0]:g}</text>',
            f'<text class="soft" x="{field_x + thumb_w * 0.75:.0f}" y="{bar_y + 22}" text-anchor="middle">0</text>',
            f'<text class="soft" x="{field_x + thumb_w}" y="{bar_y + 22}" text-anchor="end">{SCALE[1]:g}</text>']
    out.append("</svg>")
    with open(os.path.join(HERE, "hero.svg"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")


if __name__ == "__main__":
    main(sys.argv[1])

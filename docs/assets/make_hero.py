"""Draws docs/assets/hero.svg, the README's picture, from the AirfRANS study.

    python docs/assets/make_hero.py AIRFRANS.gamut

AIRFRANS.gamut is the 100-run subset of AirfRANS (Bonnet et al., NeurIPS
2022; ODbL) that bench/airfrans.py fetches, turned into one file by
`gamut-vtk import`. Four runs, spread over angle of attack, are read from
it with gamut and rendered with PyVista: the flow speed around each
airfoil, relative to the inflow, under the run's values from the run table.
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
SCALE = (0.4, 1.6)            # speed over inflow speed; white is the inflow
VIEW = (0.55, 0.0, 0.32)      # centre x, centre y and half height, in chords
STYLE = """<style>
    .ink { fill: #1F2328; } .soft { fill: #59636E; } .frame { fill: none; stroke: #D0D7DE; }
    .page { fill: #FFFFFF; }
    @media (prefers-color-scheme: dark) {
      .page { fill: #0D1117; } .ink { fill: #E6EDF3; } .soft { fill: #9198A1; } .frame { stroke: #30363D; }
    }
    text { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; font-size: 12px; }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
    .h { font-weight: 600; }
  </style>"""


def render(study, row: int, width: int, height: int) -> str:
    """One run's speed field near the airfoil, as a JPEG data URI."""
    points = study.get_points(row=row)
    types, offsets, connectivity = study.get_cells(row=row)
    cells = np.insert(connectivity, offsets[:-1], np.diff(offsets))
    xyz = points if points.shape[1] == 3 else np.c_[points, np.zeros(len(points))]
    grid = pv.UnstructuredGrid(cells, types, xyz)
    inflow = float(study.get_parameter("inflow_speed", rows=[row])[0])
    speed = np.hypot(study.get_field("U_x", rows=[row]), study.get_field("U_y", rows=[row]))
    grid.point_data["speed"] = speed.ravel() / inflow
    plotter = pv.Plotter(off_screen=True, window_size=(width, height))
    plotter.add_mesh(grid, scalars="speed", cmap="RdBu_r", clim=SCALE, lighting=False,
                     show_scalar_bar=False)
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


def colour_bar(x: float, y: float, width: float) -> list[str]:
    import matplotlib
    stops = "".join(f'<stop offset="{k / 10:.1f}" stop-color="{matplotlib.colors.to_hex(c)}"/>'
                    for k, c in enumerate(matplotlib.colormaps["RdBu_r"](np.linspace(0, 1, 11))))
    lo, hi = SCALE
    return [f'<defs><linearGradient id="speed">{stops}</linearGradient></defs>',
            f'<rect x="{x}" y="{y}" width="{width}" height="8" fill="url(#speed)"/>',
            f'<text class="soft" x="{x}" y="{y + 22}">{lo}</text>',
            f'<text class="soft" x="{x + width / 2}" y="{y + 22}" text-anchor="middle">1, the inflow</text>',
            f'<text class="soft" x="{x + width}" y="{y + 22}" text-anchor="end">{hi}</text>',
            f'<text class="soft" x="{x - 10}" y="{y + 8}" text-anchor="end">speed over inflow speed</text>']


def main(path: str) -> None:
    width, gap, top, caption = 760, 16, 52, 24
    tile_w = (width - gap) / 2
    tile_h = round(tile_w * VIEW[2] / (VIEW[2] * 2 * 1.136))   # the view's aspect, 2.27 : 1
    with gamut.open(path) as study:
        alpha = study.get_parameter("angle_of_attack")
        order = np.argsort(alpha)
        rows = [int(order[round(q * (len(order) - 1))]) for q in (0.03, 0.35, 0.65, 0.97)]
        tiles = []
        for row in rows:
            image = render(study, row, int(2 * tile_w), int(2 * tile_h))
            values = (f"run {int(study.get_row_ids(rows=[row])[0])}",
                      f"α {float(alpha[row]):.1f}°",
                      f"{float(study.get_parameter('inflow_speed', rows=[row])[0]):.0f} m/s",
                      f"{float(study.get_parameter('naca_t', rows=[row])[0]):.0f} % thick",
                      str(study.get_label("split", rows=[row])[0]))
            tiles.append((image, values))
        runs = study.row_count
        nodes = int(np.mean([len(study.get_points(row=r)) for r in range(runs)]))
    size = os.path.getsize(path)
    height = top + 2 * (tile_h + caption + gap) + 30
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" '
           f'height="{height}" role="img" aria-label="Flow speed around four airfoils from one study file, '
           f'each with its angle of attack, inflow speed, thickness and split">', STYLE,
           '<rect class="page" width="100%" height="100%"/>',
           f'<text class="ink mono h" x="0" y="18">{os.path.basename(path)}</text>',
           f'<text class="soft" x="0" y="38">{runs} RANS runs around NACA airfoils, each on its own mesh of '
           f'about {round(nodes, -3):,} nodes; {size / 1e6:.0f} MB</text>']
    for k, (image, values) in enumerate(tiles):
        x = (k % 2) * (tile_w + gap)
        y = top + (k // 2) * (tile_h + caption + gap)
        out.append(f'<image href="{image}" x="{x:.1f}" y="{y}" width="{tile_w:.1f}" height="{tile_h}"/>')
        out.append(f'<rect class="frame" x="{x + 0.5:.1f}" y="{y + 0.5}" width="{tile_w - 1:.1f}" '
                   f'height="{tile_h - 1}"/>')
        out.append(f'<text class="ink" x="{x:.1f}" y="{y + tile_h + 17}"><tspan class="mono">{values[0]}</tspan>'
                   + "".join(f'<tspan class="soft">  ·  </tspan>{v}' for v in values[1:]) + '</text>')
    out += colour_bar(width - 300, height - 30, 300)
    out.append("</svg>")
    with open(os.path.join(HERE, "hero.svg"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")


if __name__ == "__main__":
    main(sys.argv[1])

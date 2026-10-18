"""Draws the README's picture from a real study, read with gamut.

    python docs/assets/make_hero.py STUDY.gamut

The study is the capsule family of docs/benchmarks.md (not public). It writes
docs/assets/hero.svg, one run of every shape coloured by its heat flux, and
docs/assets/hero-table.svg, four rows of the run table beside their two
surface fields. Renders are PyVista's, embedded as PNG.
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
def _colormap(name: str):
    """A matplotlib colormap without its darkest eighth, which vanishes on a dark page."""
    import matplotlib
    from matplotlib.colors import ListedColormap
    return ListedColormap(matplotlib.colormaps[name](np.linspace(0.12, 1.0, 256)))


FIELDS = [("pressure_coefficient", "pressure coefficient", "viridis"),
          ("heat_flux_ratio", "heat flux ratio", "inferno")]
COLUMNS = [("row", "run", "{:d}"), ("member", "shape", "{}"), ("mach", "Mach", "{:.1f}"),
           ("alpha", "α", "{:.1f}°"), ("beta", "β", "{:.1f}°"),
           ("axial_force_coefficient", "C<tspan baseline-shift=\"sub\" font-size=\"9\">A</tspan>", "{:.3f}"),
           ("split", "split", "{}")]
STYLE = """<style>
    .ink { fill: #1F2328; } .soft { fill: #59636E; } .rule { stroke: #D0D7DE; stroke-width: 1; }
    .page { fill: #FFFFFF; }
    @media (prefers-color-scheme: dark) {
      .page { fill: #0D1117; } .ink { fill: #E6EDF3; } .soft { fill: #9198A1; } .rule { stroke: #30363D; }
    }
    text { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; font-size: 12px; }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; }
    .h { font-weight: 600; }
  </style>"""


def pick(study) -> list[int]:
    """Four runs on four different shapes, from nose-down to nose-up."""
    alpha = study.get_parameter("alpha")
    member = study.get_label("member")
    chosen, seen = [], set()
    for target in (-12.0, -3.0, 6.0, 13.0):
        for row in np.argsort(np.abs(alpha - target)):
            if member[row] not in seen:
                chosen.append(int(row))
                seen.add(member[row])
                break
    return chosen


CAMERA: list = []          # the first render's camera, reused so every shape is to one scale


def render(points, cells, values, cmap, clim, camera=CAMERA, eye=(-3.0, -6.0, -4.5),
           size=(520, 460)) -> Image.Image:
    """One surface, seen from in front of and beside the heat shield."""
    types, offsets, connectivity = cells
    faces = np.hstack([np.r_[offsets[k + 1] - offsets[k], connectivity[offsets[k]:offsets[k + 1]]]
                       for k in range(len(types))])
    mesh = pv.PolyData(np.asarray(points), faces)
    mesh.point_data["v"] = values
    plotter = pv.Plotter(off_screen=True, window_size=size)
    plotter.add_mesh(mesh, scalars="v", cmap=_colormap(cmap), clim=clim, smooth_shading=True,
                     show_scalar_bar=False, ambient=0.35, diffuse=0.7, specular=0.1)
    if not camera:
        plotter.camera_position = [eye, (0.0, 0.0, 1.2), (0.0, 0.0, 1.0)]
        plotter.reset_camera()
        plotter.camera.zoom(0.9)
        camera.append(plotter.camera_position)
    plotter.camera_position = camera[0]
    image = Image.fromarray(plotter.screenshot(transparent_background=True, return_img=True))
    plotter.close()
    return image


def crop_all(images: list[Image.Image], pad: int = 6) -> tuple[list[str], float]:
    """Crops every render to the box that holds all of them, as PNG data URIs,
    with the box's height over width."""
    boxes = [im.getbbox() for im in images]
    box = (max(min(b[0] for b in boxes) - pad, 0), max(min(b[1] for b in boxes) - pad, 0),
           max(b[2] for b in boxes) + pad, max(b[3] for b in boxes) + pad)
    return [png(im.crop(box)) for im in images], (box[3] - box[1]) / (box[2] - box[0])


def png(image: Image.Image, width: int | None = None) -> str:
    """A PNG data URI, at most `width` pixels wide, in 128 colours."""
    if width and image.width > width:
        image = image.resize((width, round(image.height * width / image.width)), Image.LANCZOS)
    buffer = io.BytesIO()
    image.quantize(128, method=Image.Quantize.FASTOCTREE).save(buffer, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def table_figure(path: str) -> None:
    with gamut.open(path) as study:
        rows = pick(study)
        size = os.path.getsize(path)
        n_members = len(study.categories("member"))
        n_nodes = len(study.get_points(row=0))
        cells = study.get_cells(row=0)
        order = sorted(rows)                       # reads take increasing positions
        values = {name: study.get_field(name, rows=order)[[order.index(r) for r in rows]]
                  for name, _, _ in FIELDS}
        clims = {name: (float(np.nanpercentile(v, 1)), float(np.nanpercentile(v, 99)))
                 for name, v in values.items()}
        table = []
        for k, row in enumerate(rows):
            cells_text = []
            for name, _, fmt in COLUMNS:
                if name == "row":
                    value = int(study.get_row_ids(rows=row))
                elif name in ("member", "split"):
                    value = str(study.get_label(name, rows=row)).removesuffix(".step")
                elif name == "axial_force_coefficient":
                    value = float(study.get_scalar(name, rows=row))
                else:
                    value = float(study.get_parameter(name, rows=row))
                cells_text.append(fmt.format(value))
            images = [render(study.get_points(row=row), cells, values[name][k], cmap, clims[name])
                      for name, _, cmap in FIELDS]
            table.append((cells_text, images))
        total = study.row_count
    uris, aspect = crop_all([im for _, images in table for im in images])
    table = [(text, uris[2 * k:2 * k + 2]) for k, (text, _) in enumerate(table)]

    width, top, thumb = 760, 58, 120
    row_h = round(thumb * aspect) + 16
    xs = [0, 50, 170, 226, 286, 346, 410]
    field_x = [470, 470 + thumb + 40]
    height = top + 24 + row_h * len(table) + 34
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" '
           f'height="{height}" role="img" aria-label="Four rows of a capsule family study: each run\'s '
           f'inputs, a result and its split, beside its surface pressure and heating">', STYLE,
           '<rect class="page" width="100%" height="100%"/>',
           f'<text class="ink mono h" x="0" y="20">{os.path.basename(path)}</text>',
           f'<text class="soft" x="0" y="40">{total:,} runs of {n_members} capsule shapes, '
           f'two fields on {n_nodes:,} nodes each, {size / 1e6:.0f} MB</text>']
    y = top + 14
    for (_, label, _), x in zip(COLUMNS, xs):
        out.append(f'<text class="soft" x="{x}" y="{y}">{label}</text>')
    for (_, label, _), x in zip(FIELDS, field_x):
        out.append(f'<text class="soft" x="{x + thumb / 2:.0f}" y="{y}" text-anchor="middle">{label}</text>')
    out.append(f'<line class="rule" x1="0" y1="{y + 8}" x2="{width}" y2="{y + 8}"/>')
    for k, (cells_text, images) in enumerate(table):
        y0 = top + 24 + k * row_h
        for text, x in zip(cells_text, xs):
            cls = "ink mono" if x in (0, 46) else "ink"
            out.append(f'<text class="{cls}" x="{x}" y="{y0 + row_h / 2 + 4:.0f}">{text}</text>')
        for image, x in zip(images, field_x):
            out.append(f'<image href="{image}" x="{x}" y="{y0 + (row_h - thumb * aspect) / 2:.0f}" '
                       f'width="{thumb}" height="{thumb * aspect:.0f}"/>')
        out.append(f'<line class="rule" x1="0" y1="{y0 + row_h}" x2="{width}" y2="{y0 + row_h}"/>')
    out.append(f'<text class="soft" x="0" y="{height - 10}">and {total - len(table):,} more rows; '
               f'every field is one block of runs × nodes</text>')
    out.append("</svg>")
    with open(os.path.join(HERE, "hero-table.svg"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")


def family_figure(path: str) -> None:
    """One run of every shape, the one nearest 10 degrees incidence, by heat flux."""
    with gamut.open(path) as study:
        alpha = study.get_parameter("alpha")
        member = study.get_label("member")
        names = study.categories("member")
        rows = []
        for name in names:
            mine = np.flatnonzero(member == name)
            rows.append(int(mine[np.argmin(np.abs(alpha[mine] - 10.0))]))
        order = sorted(rows)                       # reads take increasing positions
        heat = study.get_field("heat_flux_ratio", rows=order)
        heat = heat[[order.index(r) for r in rows]]
        clim = (0.0, float(np.percentile(heat, 99.5)))
        cells = study.get_cells(row=0)
        camera: list = []
        images = [render(study.get_points(row=r), cells, heat[k], "inferno", clim, camera,
                         eye=(-2.0, -7.0, -2.5), size=(300, 300)) for k, r in enumerate(rows)]
        total, n_nodes, size = study.row_count, heat.shape[1], os.path.getsize(path)
    boxes = [im.getbbox() for im in images]
    box = (min(b[0] for b in boxes) - 2, min(b[1] for b in boxes) - 2,
           max(b[2] for b in boxes) + 2, max(b[3] for b in boxes) + 2)
    cols, width, top = 11, 760, 50
    w = width / cols
    h = w * (box[3] - box[1]) / (box[2] - box[0])
    lines = -(-len(images) // cols)
    height = top + lines * (h + 4) + 28
    runs_each = total // len(names)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height:.0f}" width="{width}" '
           f'height="{height:.0f}" role="img" aria-label="{len(names)} capsule shapes from one study file, '
           f'each coloured by its surface heat flux">', STYLE, '<rect class="page" width="100%" height="100%"/>',
           f'<text class="ink mono h" x="0" y="18">{os.path.basename(path)}</text>',
           f'<text class="soft" x="0" y="38">{len(names)} capsule shapes on one mesh topology, heat flux ratio '
           f'at {n_nodes:,} nodes; one of each shape\'s {runs_each} runs, the one nearest 10° incidence</text>']
    for k, image in enumerate(images):
        x, y = (k % cols) * w, top + (k // cols) * (h + 4)
        out.append(f'<image href="{png(image.crop(box), 2 * round(w))}" x="{x:.1f}" y="{y:.1f}" '
                   f'width="{w:.1f}" height="{h:.1f}"/>')
    out.append(f'<text class="soft" x="0" y="{height - 8:.0f}">{total:,} runs in {size / 1e6:.0f} MB. '
               f'Each field is one block of runs × nodes, and node k is the same point on every shape.</text>')
    out.append("</svg>")
    with open(os.path.join(HERE, "hero.svg"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")


if __name__ == "__main__":
    family_figure(sys.argv[1])
    table_figure(sys.argv[1])

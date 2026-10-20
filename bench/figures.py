"""The benchmark page's figures and tables, from the results.

    python bench/figures.py            # rewrite docs/assets/bench-*.svg and the tables
    python bench/figures.py --check    # exit 1 if the page is not what the results give

Tables go into docs/benchmarks.md between `<!-- results: NAME -->` and
`<!-- end -->`; nothing else on the page is touched.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RESULTS = os.path.join(HERE, "results")
PAGE = os.path.join(ROOT, "docs", "benchmarks.md")
ASSETS = os.path.join(ROOT, "docs", "assets")

NAMES = {"gamut": "Gamut", "gamut_threads": "Gamut, 4 threads", "vtk_folder": "VTK folder", "vtk_zip": "VTK folder, zipped",
         "hdf5_per_run": "HDF5, a group per run", "netcdf": "netCDF-4 (xarray)",
         "zarr": "Zarr (xarray)", "parquet": "Parquet, run table only", "vtkhdf": "VTKHDF, a step per run",
         "npz_per_run": "NumPy, a file per run", "npy": "NumPy arrays, uncompressed"}
NAMES.update({"exodus": "Exodus II, native defaults", "exodus_gzip": "Exodus II, gzip 1 + shuffle",
              "cgns": "CGNS, native defaults", "pmsh": "PhysicsNeMo-Mesh (PMSH)",
              "h5py": "Storage baseline: same file via h5py"})
READS = {"open": "Open", "one_run": "One run", "one_node": "One node, every run",
         "region": "A region, every run", "query": "Runs by condition"}

STYLE = """<style>
    .ink { fill: #1F2328; } .soft { fill: #59636E; } .grid { stroke: #D0D7DE; stroke-width: 1; }
    .bar { fill: #8C959F; } .ours { fill: #4A9FF5; } .page { fill: #FFFFFF; }
    @media (prefers-color-scheme: dark) {
      .page { fill: #0D1117; } .ink { fill: #E6EDF3; } .soft { fill: #9198A1; } .grid { stroke: #30363D; } .bar { fill: #6E7681; }
    }
    text { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; font-size: 12px; }
    .h { font-size: 13px; font-weight: 600; }
  </style>"""


def load(name: str) -> dict:
    with open(os.path.join(RESULTS, name + ".json")) as fh:
        return json.load(fh)


def seconds(s: float) -> str:
    if s == 0:
        return "0"
    if s < 1e-3:
        return f"{s * 1e6:.0f} µs"
    if s < 1:
        return f"{s * 1e3:.3g} ms"
    return f"{s:.3g} s"


def megabytes(b: int) -> str:
    return f"{b / 1e9:.3g} GB" if b >= 1e9 else f"{b / 1e6:.3g} MB"


def bars(title: str, subtitle: str, items: list[tuple[str, float | None, str, bool]],
         time_axis: bool) -> str:
    """A horizontal bar chart: (label, value, value text, ours) per bar; a
    value of None makes the label a group heading. Times spanning more than
    thirty-fold are drawn on a logarithmic axis."""
    width, left, right, row = 680, 190, 90, 26
    top = 52
    height = top + row * len(items) + (30 if time_axis else 8)
    span = width - left - right
    values = [v for _, v, _, _ in items if v is not None]
    log = time_axis and max(values) / min(values) > 30
    if log:
        lo = 10 ** math.floor(math.log10(min(values)))
        hi = 10 ** math.ceil(math.log10(max(values)))
        scale = lambda v: span * (math.log10(v) - math.log10(lo)) / (math.log10(hi) - math.log10(lo))
        ticks = [lo * 10 ** k for k in range(round(math.log10(hi / lo)) + 1)]
    else:
        hi = max(values) * 1.05
        scale = lambda v: span * v / hi
        step = 10 ** math.floor(math.log10(hi)) if time_axis else 0
        if step and hi / step < 3:
            step /= 2
        ticks = [k * step for k in range(int(hi / step) + 1)] if step else []
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" '
           f'height="{height}" role="img" aria-label="{title}">', STYLE,
           '<rect class="page" width="100%" height="100%"/>',
           f'<text class="ink h" x="0" y="18">{title}</text>',
           f'<text class="soft" x="0" y="36">{subtitle}</text>']
    for t in ticks:
        x = left + scale(t)
        out.append(f'<line class="grid" x1="{x:.1f}" y1="{top - 6}" x2="{x:.1f}" '
                   f'y2="{top + row * len(items)}"/>')
        out.append(f'<text class="soft" x="{x:.1f}" y="{top + row * len(items) + 18}" '
                   f'text-anchor="middle">{seconds(t)}</text>')
    for i, (label, value, text, ours) in enumerate(items):
        y = top + i * row
        if value is None:
            out.append(f'<text class="ink h" x="0" y="{y + 16}">{label}</text>')
            continue
        w = max(scale(value), 2)
        out.append(f'<text class="ink" x="{left - 10}" y="{y + 15}" text-anchor="end">{label}</text>')
        out.append(f'<rect class="{"ours" if ours else "bar"}" x="{left}" y="{y + 4}" '
                   f'width="{w:.1f}" height="16" rx="2"/>')
        out.append(f'<text class="soft" x="{left + w + 6:.1f}" y="{y + 16}">{text}</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def size_figure(cases: list[tuple[str, dict]]) -> str:
    items: list[tuple[str, float | None, str, bool]] = []
    for label, r in cases:
        base = r["formats"]["vtk_folder"]["bytes"]
        items.append((label, None, "", False))
        for fmt in ("gamut", "vtk_folder", "vtk_zip", "vtkhdf", "hdf5_per_run", "netcdf", "zarr",
                    "npz_per_run", "npy"):
            if fmt in r["formats"]:
                f = r["formats"][fmt]
                items.append((NAMES[fmt], f["bytes"] / base, megabytes(f["bytes"]),
                              fmt == "gamut"))
    return bars("Size on disk", "each study against the folder of VTK files it came as; shorter "
                "is smaller", items, time_axis=False)


def read_figure(r: dict, read: str, title: str, subtitle: str) -> str:
    items = [(NAMES[fmt], f[read]["median_s"], seconds(f[read]["median_s"]), fmt.startswith("gamut"))
             for fmt, f in r["formats"].items() if read in f]
    items.sort(key=lambda x: x[1])
    return bars(title, subtitle, items, time_axis=True)


WORDS = {5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine"}


def summary_figure(r: dict) -> str:
    """The README's figure: one study, four measures, the same formats in
    the same order in every panel, each panel on its own linear scale."""
    formats = [f for f in ("gamut", "hdf5_per_run", "netcdf", "vtkhdf", "zarr", "npz_per_run", "npy",
                           "vtk_folder") if f in r["formats"]]
    labels = {"gamut": "Gamut", "hdf5_per_run": "HDF5, a group per run", "netcdf": "netCDF-4",
              "vtkhdf": "VTKHDF", "zarr": "Zarr", "npz_per_run": "NumPy, a file per run",
              "npy": "NumPy, uncompressed", "vtk_folder": "VTK files"}
    panels = [[("Size on disk", lambda f: f["bytes"], lambda f: megabytes(f["bytes"])),
               ("Read one run", lambda f: f["one_run"]["median_s"], lambda f: seconds(f["one_run"]["median_s"]))],
              [("Choose runs by condition, read a result of each", lambda f: f["query"]["median_s"],
                lambda f: seconds(f["query"]["median_s"])),
               ("Read one node in every run", lambda f: f["one_node"]["median_s"],
                lambda f: seconds(f["one_node"]["median_s"]))]]
    width, left, gap, row, label_room = 760, 150, 28, 22, 64
    panel = (width - left - gap) / 2
    band = 30 + row * len(formats) + 18
    top = 54
    height = top + band * len(panels)
    shape = r["shape"]
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" '
           f'height="{height}" role="img" aria-label="Size and read times of one study in eight formats">', STYLE, '<rect class="page" width="100%" height="100%"/>',
           f'<text class="ink h" x="0" y="18">One study in {WORDS[len(formats)]} formats</text>',
           f'<text class="soft" x="0" y="36">{shape["runs"]:,} runs of a capsule family on one '
           f'{shape["nodes"]:,}-node mesh; shorter is better</text>']
    for b, pair in enumerate(panels):
        y0 = top + b * band
        for i, fmt in enumerate(formats):
            out.append(f'<text class="ink" x="{left - 10}" y="{y0 + 30 + i * row + 14}" '
                       f'text-anchor="end">{labels[fmt]}</text>')
        for c, (title, value, text) in enumerate(pair):
            x0 = left + c * (panel + gap)
            out.append(f'<text class="ink h" x="{x0:.1f}" y="{y0 + 18}">{title}</text>')
            hi = max(value(r["formats"][fmt]) for fmt in formats)
            for i, fmt in enumerate(formats):
                f = r["formats"][fmt]
                w = (panel - label_room) * value(f) / hi
                y = y0 + 30 + i * row
                out.append(f'<rect class="{"ours" if fmt == "gamut" else "bar"}" x="{x0:.1f}" y="{y + 3}" '
                           f'width="{w:.1f}" height="15" rx="2"/>')
                out.append(f'<text class="soft" x="{x0 + w + 6:.1f}" y="{y + 15}">{text(f)}</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def table(r: dict, reads: list[str]) -> str:
    head = "| Format | Size | Write | " + " | ".join(READS[x] for x in reads) + " |"
    rule = "|---|---:|---:|" + "---:|" * len(reads)
    rows = [head, rule]
    for fmt, f in r["formats"].items():
        cells = [f"**{NAMES[fmt]}**" if fmt.startswith("gamut") else NAMES[fmt], megabytes(f["bytes"]),
                 seconds(f["write_s"]) if f.get("write_s") else "—"]
        cells += [seconds(f[x]["median_s"]) if x in f else "—" for x in reads]
        rows.append("| " + " | ".join(cells) + " |")
    return "\n".join(rows)


def study_summary(capsule: dict, xfoil: dict) -> str:
    """Paired dataset bars, each a format's size or time divided by Gamut's on
    one thread on the same dataset, so both datasets share one linear axis
    with Gamut as the line at 1x. Rows run best first by the capsule result;
    a bar past the axis is cut and carries its ratio; the right-hand column
    gives the measured values."""
    width, gap, pad, limit, span = 760, 20, 14, 3, 246
    panel_width = (width - gap) // 2
    row, bar, bar_gap = 42, 9, 2
    datasets = [("Capsule family · triangulated", capsule, "capsule"), ("XFOIL airfoil sweep", xfoil, "xfoil")]
    formats = [("gamut", "Gamut · 1 thread"), ("gamut_threads", "Gamut · 4 threads"),
               ("exodus_gzip", "Exodus II · gzip 1 + shuffle"),
               ("cgns", "CGNS · uncompressed defaults"), ("pmsh", "PhysicsNeMo-Mesh · CPU")]
    panels = [("File size", "bytes"), ("Read one run", "one_run"),
              ("Read one node across every run", "one_node"), ("Select runs and read a result", "query")]

    def measured(r, fmt, metric):
        record = r["formats"][fmt]
        return record["bytes"] if metric == "bytes" else record[metric]["median_s"]

    rows = []
    for _, metric in panels:
        shown = [(fmt, "Gamut" if metric == "bytes" and fmt == "gamut" else label) for fmt, label in formats
                 if all(fmt in r["formats"] for _, r, _ in datasets)
                 and not (metric == "bytes" and fmt == "gamut_threads")]    # the same file as one thread
        rows.append(sorted(shown, key=lambda f: measured(capsule, f[0], metric) / measured(capsule, "gamut", metric)))
    band = [44 + max(len(rows[2 * b]), len(rows[2 * b + 1])) * row + 26 for b in (0, 1)]
    top = 92
    height = top + band[0] + band[1] + 40
    style = """<style>
      text { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; }
      .page { fill: #FFFFFF; } .ink { fill: #1F2328; } .muted { fill: #59636E; }
      .capsule { fill: #0070DC; } .xfoil { fill: #74B5EB; }
      .grid { stroke: #E1E6EC; stroke-width: 1; } .base { stroke: #1F2328; stroke-width: 1.5; }
      .cut { stroke: #FFFFFF; stroke-width: 2; fill: none; }
      .title { font-size: 18px; font-weight: 600; } .heading { font-size: 13px; font-weight: 600; }
      .name { font-size: 12px; } .ours { font-weight: 600; } .small { font-size: 11px; }
      .value { font-size: 11px; font-variant-numeric: tabular-nums; }
      @media (prefers-color-scheme: dark) {
        .page { fill: #0D1117; } .ink { fill: #E6EDF3; } .muted { fill: #9AA6B4; }
        .capsule { fill: #369BF7; } .xfoil { fill: #95CEFA; }
        .grid { stroke: #293440; } .base { stroke: #E6EDF3; } .cut { stroke: #0D1117; }
      }
    </style>"""
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
           f'width="{width}" height="{height}" role="img" aria-label="Study size and read time relative to Gamut">',
           '<title>Size and read time against Gamut</title>',
           '<desc>Four horizontal bar charts compare formats on two datasets. Dark blue is the triangulated capsule '
           'family; light blue is the XFOIL sweep. Every format uses the same transformed capsule mesh. Each bar is '
           'the format\'s size or time divided by Gamut\'s on one thread on the same dataset, on a linear axis from '
           f'0 to {limit} times; longer bars are cut and labelled with their ratio. Measured values are labelled. '
           'Accessible tables and methodology are in the benchmark page.</desc>',
           style, '<rect class="page" width="100%" height="100%"/>',
           '<text class="ink title" x="0" y="20">Size and read time against Gamut</text>']
    for x, (name, result, colour) in zip((0, panel_width + gap), datasets):
        shape = result["shape"]
        out += [f'<rect class="{colour}" x="{x}" y="37" width="12" height="8" rx="1"/>',
                f'<text class="ink small" x="{x+20}" y="45">{name} · {shape["runs"]:,} runs · {shape["nodes"]:,} nodes</text>']
    out.append('<text class="muted small" x="0" y="68">Bars are relative to Gamut on one thread (the line at 1×) on the '
               'same dataset; labels are measured values. Shorter is smaller or faster.</text>')
    for panel, ((title, metric), shown) in enumerate(zip(panels, rows)):
        x = (panel % 2) * (panel_width + gap) + pad
        y = top + (band[0] if panel // 2 else 0)
        right = x - pad + panel_width - pad
        bottom = y + 30 + len(shown) * row
        out.append(f'<text class="ink heading" x="{x}" y="{y+16}">{title}</text>')
        for k in range(limit + 1):
            tx = x + span * k / limit
            for i in range(len(shown)):
                gy = y + 30 + i * row + 17
                out.append(f'<path class="{"base" if k == 1 else "grid"}" d="M{tx:.1f} {gy} V{gy + 2 * bar + bar_gap + 6}"/>')
            out.append(f'<text class="muted small" x="{tx:.1f}" y="{bottom+15}" text-anchor="middle">{k}{"×" if k else ""}</text>')
        for i, (fmt, label) in enumerate(shown):
            ty = y + 30 + i * row
            out.append(f'<text class="ink name{" ours" if fmt.startswith("gamut") else ""}" x="{x}" y="{ty+14}">{label}</text>')
            for j, (_, result, colour) in enumerate(datasets):
                value = measured(result, fmt, metric)
                ratio = value / measured(result, "gamut", metric)
                length = max(span * min(ratio, limit) / limit, 1.5)
                by = ty + 20 + j * (bar + bar_gap)
                text = megabytes(value) if metric == "bytes" else seconds(value)
                out.append(f'<rect class="{colour}" x="{x}" y="{by}" width="{length:.1f}" height="{bar}" rx="1"/>')
                if ratio > limit:
                    cx = x + length - 10
                    out.append(f'<path class="cut" d="M{cx-2:.1f} {by+bar+1} L{cx+2:.1f} {by-1} M{cx+3:.1f} {by+bar+1} L{cx+7:.1f} {by-1}"/>')
                    text += f" · {ratio:.0f}×"
                out.append(f'<text class="ink value" x="{right}" y="{by+bar-1}" text-anchor="end">{text}</text>')
    out += [f'<text class="muted small" x="0" y="{height-26}">Apple M3 · warm-cache medians of five · each read opens and closes the file</text>',
            f'<text class="muted small" x="0" y="{height-8}">PMSH cannot preserve quads. Capsule bars use triangles for every format. Sizes include CSV/schema companions.</text>',
            '</svg>']
    return "\n".join(out) + "\n"


def machine_line(r: dict) -> str:
    m = r["machine"]
    p = m.get("packages", {})
    memory = f"{int(m['memory_bytes']) / 2**30:.0f} GB" if m.get("memory_bytes") else ""
    versions = ", ".join(f"{k} {v}" for k, v in p.items())
    return (f"{m.get('cpu', '')}, {memory}, {m.get('system', '')}; Python {m['python']}; "
            f"{versions}; Gamut built from {m.get('source', 'an unrecorded commit')}.")


def generated() -> tuple[dict[str, str], dict[str, str]]:
    capsule = load("capsule_incidence")
    airfrans = load("airfrans")
    native = load("capsule_native")
    triangulated = load("capsule_tri_native")
    xfoil = load("xfoil_native")
    figures = {
        "bench-study.svg": study_summary(triangulated, xfoil),
        "bench-summary.svg": summary_figure(capsule),
        "bench-size.svg": size_figure([("The capsule family", capsule), ("AirfRANS", airfrans)]),
        "bench-one-node.svg": read_figure(
            capsule, "one_node", "One node across every run",
            f"capsule family, {capsule['shape']['runs']:,} runs; median of five, shorter is faster"),
        "bench-one-run.svg": read_figure(
            airfrans, "one_run", "One run's points and pressure",
            f"AirfRANS, {airfrans['shape']['runs']} runs on their own meshes; median of five, "
            "shorter is faster"),
    }
    tables = {
        "capsule": table(capsule, ["open", "one_run", "one_node", "region", "query"]),
        "airfrans": table(airfrans, ["open", "one_run", "query"]),
        "machine": machine_line(capsule),
        "capsule_native": table(native, ["one_run", "one_node", "region", "query"]),
        "capsule_tri_native": table(triangulated, ["one_run", "one_node", "region", "query"]),
        "xfoil_native": table(xfoil, ["one_run", "one_node", "region", "query"]),
        "machine_native": machine_line(xfoil),
    }
    return figures, tables


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    figures, tables = generated()
    with open(PAGE, encoding="utf-8") as fh:
        page = fh.read()
    new = page
    for name, text in tables.items():
        start = new.find(f"<!-- results: {name} -->\n")
        if start < 0:
            print(f"the page has no `<!-- results: {name} -->` marker")
            return 1
        start += len(f"<!-- results: {name} -->\n")
        end = new.find("<!-- end -->", start)        # this block's own end
        new = new[:start] + text + "\n" + new[end:]
    stale = [n for n, svg in figures.items()
             if not os.path.exists(os.path.join(ASSETS, n))
             or open(os.path.join(ASSETS, n), encoding="utf-8").read() != svg]
    if args.check:
        if new != page or stale:
            print("the benchmark page or figures differ from the results:", "page" if new != page
                  else "", *stale)
            return 1
        return 0
    with open(PAGE, "w", encoding="utf-8") as fh:
        fh.write(new)
    for name, svg in figures.items():
        with open(os.path.join(ASSETS, name), "w", encoding="utf-8") as fh:
            fh.write(svg)
    return 0


if __name__ == "__main__":
    sys.exit(main())

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

NAMES = {"mestra": "mestra", "mestra_threads": "mestra, 4 threads", "vtk_folder": "VTK folder", "vtk_zip": "VTK folder, zipped",
         "hdf5_per_run": "HDF5, a group per run", "netcdf": "netCDF-4 (xarray)",
         "zarr": "Zarr (xarray)", "parquet": "Parquet, run table only"}
READS = {"open": "Open", "one_run": "One run", "one_node": "One node, every run",
         "region": "A region, every run", "query": "Runs by condition"}

STYLE = """<style>
    .ink { fill: #1F2328; } .soft { fill: #59636E; } .grid { stroke: #D0D7DE; stroke-width: 1; }
    .bar { fill: #8C959F; } .ours { fill: #4A9FF5; }
    @media (prefers-color-scheme: dark) {
      .ink { fill: #E6EDF3; } .soft { fill: #9198A1; } .grid { stroke: #30363D; } .bar { fill: #6E7681; }
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
        for fmt in ("mestra", "vtk_folder", "vtk_zip", "hdf5_per_run", "netcdf", "zarr"):
            if fmt in r["formats"]:
                f = r["formats"][fmt]
                items.append((NAMES[fmt], f["bytes"] / base, megabytes(f["bytes"]),
                              fmt == "mestra"))
    return bars("Size on disk", "each study against the folder of VTK files it came as; shorter "
                "is smaller", items, time_axis=False)


def read_figure(r: dict, read: str, title: str, subtitle: str) -> str:
    items = [(NAMES[fmt], f[read]["median_s"], seconds(f[read]["median_s"]), fmt.startswith("mestra"))
             for fmt, f in r["formats"].items() if read in f]
    items.sort(key=lambda x: x[1])
    return bars(title, subtitle, items, time_axis=True)


def table(r: dict, reads: list[str]) -> str:
    head = "| Format | Size | Write | " + " | ".join(READS[x] for x in reads) + " |"
    rule = "|---|---:|---:|" + "---:|" * len(reads)
    rows = [head, rule]
    for fmt, f in r["formats"].items():
        cells = [f"**{NAMES[fmt]}**" if fmt.startswith("mestra") else NAMES[fmt], megabytes(f["bytes"]),
                 seconds(f["write_s"]) if f.get("write_s") else "—"]
        cells += [seconds(f[x]["median_s"]) if x in f else "—" for x in reads]
        rows.append("| " + " | ".join(cells) + " |")
    return "\n".join(rows)


def machine_line(r: dict) -> str:
    m = r["machine"]
    p = m.get("packages", {})
    memory = f"{int(m['memory_bytes']) / 2**30:.0f} GB" if m.get("memory_bytes") else ""
    versions = ", ".join(f"{k} {v}" for k, v in p.items())
    return (f"{m.get('cpu', '')}, {memory}, {m.get('system', '')}; Python {m['python']}; "
            f"{versions}; mestra built from {m.get('source', 'an unrecorded commit')}.")


def generated() -> tuple[dict[str, str], dict[str, str]]:
    capsule = load("capsule_incidence")
    airfrans = load("airfrans")
    figures = {
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

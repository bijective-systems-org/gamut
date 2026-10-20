"""Compare native simulation formats on one shared-topology study.

python bench/study_formats.py run STUDY.gamut WORK_DIR RESULT.json
    --field cp --row 100 --node 12 --region 0:80
    --where 'alpha > 5 and reynolds > 1000000' --scalar cl

Each native file holds one geometry and all its runs. A CSV manifest maps
rows to geometry and solution/time index; schema.json records declarations.
PMSH stores each point field as nodes x runs, using official Mesh.save/load.
The matched h5py baseline reads the very same Gamut file, not another layout.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import time
from importlib import metadata

import numpy as np

from common import machine, run_child, size_of, timed
from native_formats import CGNS, Exodus
from shared_mesh import load, parse_where, write_gamut

FORMATS = ("gamut", "gamut_threads", "exodus", "exodus_gzip", "cgns", "pmsh", "h5py")


def path_of(work, fmt):
    return Path(work) / {"gamut": "study.gamut", "gamut_threads": "study.gamut",
                         "h5py": "study.gamut"}.get(fmt, fmt)


def manifest(d):
    step = np.empty(len(d["member"]), dtype="i8")
    for m in range(len(d["points"])):
        step[d["member"] == m] = np.arange(np.count_nonzero(d["member"] == m))
    return {"geometry": d["member"], "step": step, **d["table"]}


def write_manifest(d, out):
    import pandas as pd
    pd.DataFrame(manifest(d)).to_csv(out / "runs.csv", index=False)
    (out / "schema.json").write_text(json.dumps(d["declared"], indent=1))


def read_manifest(out):
    import pandas as pd
    schema = json.loads((out / "schema.json").read_text())
    missing = {n: [""] for n, d in schema.items() if d["kind"] in ("parameter", "scalar")}
    return pd.read_csv(out / "runs.csv", float_precision="round_trip",
                       keep_default_na=False, na_values=missing)


def native_path(out, fmt, member):
    return out / f"geometry_{member:05d}.{dict(exodus='e', exodus_gzip='e', cgns='cgns', pmsh='pmsh')[fmt]}"


def write_native(d, out, fmt):
    out.mkdir()
    write_manifest(d, out)
    if fmt == "pmsh":
        import torch
        from physicsnemo.mesh import Mesh
        types, offsets, conn = d["cells"]
        kind, = np.unique(types)
        width = {3: 2, 5: 3, 10: 4}[int(kind)]  # simplices only; never triangulate one peer
        cells = torch.from_numpy(conn.reshape(-1, width).copy())
        for m, points in enumerate(d["points"]):
            mesh = Mesh(points=torch.from_numpy(points.copy()), cells=cells)
            for name, values in d["fields"].items():
                mesh.point_data[name] = torch.from_numpy(values[d["member"] == m].T.copy())
            mesh.save(native_path(out, fmt, m))
    else:
        api = CGNS() if fmt == "cgns" else Exodus(compressed=fmt == "exodus_gzip")
        for m, points in enumerate(d["points"]):
            api.write(native_path(out, fmt, m), points, d["cells"],
                      {n: a[d["member"] == m] for n, a in d["fields"].items()})


def native_field(out, fmt, table, field, field_index, rows, lo, hi):
    values = np.empty((len(rows), hi - lo), dtype="f8")
    api = (CGNS() if fmt == "cgns" else Exodus()) if fmt != "pmsh" else None
    for m in dict.fromkeys(table.geometry.iloc[rows]):
        positions = np.flatnonzero(table.geometry.iloc[rows].to_numpy() == m)
        steps = table.step.iloc[rows[positions]].to_numpy()
        path = native_path(out, fmt, m)
        if fmt == "pmsh":
            from physicsnemo.mesh import Mesh
            mesh = Mesh.load(path)
            # NumPy copy and sum below force page access, not just a mapping handle.
            values[positions] = mesh.point_data[field][lo:hi, steps].T.numpy()
        else:
            with api.opened(path) as f:
                values[positions] = api.field(f, field if fmt == "cgns" else field_index,
                                              steps, lo, hi)
    return values


def verify(d, out, fmt):
    """Untimed full ordered comparisons; scalar checksums alone can hide errors."""
    if fmt in ("gamut", "gamut_threads", "h5py"):
        other = load(str(out))
        for key in ("member",):
            np.testing.assert_equal(other[key], d[key])
        for key in ("fields", "table"):
            for name, values in d[key].items():
                np.testing.assert_equal(other[key][name], values)
        for key in ("points", "cells"):
            for got, expected in zip(other[key], d[key], strict=True):
                np.testing.assert_equal(got, expected)
        return
    table = read_manifest(out)
    for name, values in manifest(d).items():
        np.testing.assert_equal(table[name].to_numpy(), values)
    assert json.loads((out / "schema.json").read_text()) == json.loads(json.dumps(d["declared"]))
    for m, points in enumerate(d["points"]):
        path = native_path(out, fmt, m)
        if fmt == "pmsh":
            from physicsnemo.mesh import Mesh
            mesh = Mesh.load(path)
            np.testing.assert_equal(mesh.points.numpy(), points)
            np.testing.assert_equal(mesh.cells.numpy().reshape(-1), d["cells"][2])
        else:
            api = CGNS() if fmt == "cgns" else Exodus()
            with api.opened(path) as f:
                p, cells = api.mesh(f)
            np.testing.assert_equal(p, points)
            for got, expected in zip(cells, d["cells"], strict=True):
                np.testing.assert_equal(got, expected)
    rows = np.arange(len(d["member"]))
    for index, (name, values) in enumerate(d["fields"].items()):
        np.testing.assert_equal(native_field(out, fmt, table, name, index, rows,
                                             0, len(d["points"][0])), values)


def read_functions(args, fmt, out, info):
    n, nodes = info["runs"], info["nodes"]
    index = info["fields"].index(args.field)
    conditions = parse_where(args.where)
    ops = {">": np.greater, "<": np.less, ">=": np.greater_equal, "<=": np.less_equal}

    def select(table):
        keep = np.ones(n, dtype=bool)
        for name, op, value in conditions:
            keep &= ops[op](np.asarray(table[name], dtype=float), value)
        return keep

    def field(rows, lo, hi):
        if fmt in ("gamut", "gamut_threads"):
            import gamut
            with gamut.open(out, threads=4 if fmt == "gamut_threads" else 1) as s:
                return s.get_field(args.field, rows=rows, nodes=slice(lo, hi))
        if fmt == "h5py":
            import h5py
            with h5py.File(out) as f:
                selected = slice(int(rows[0]), int(rows[-1]) + 1)
                return f["mesh/node_fields/" + args.field][selected, lo:hi]
        return native_field(out, fmt, read_manifest(out), args.field, index, rows, lo, hi)

    def query():
        if fmt in ("gamut", "gamut_threads"):
            import gamut
            with gamut.open(out) as s:
                return float(np.nansum(s.get_scalar(args.scalar, rows=s.select(args.where))))
        if fmt == "h5py":
            import h5py
            with h5py.File(out) as f:
                g = f
                table = {name: g[name][:].reshape(-1) for name, _, _ in conditions}
                return float(np.nansum(g[args.scalar][:].reshape(-1)[select(table)]))
        table = read_manifest(out)
        return float(np.nansum(table[args.scalar].to_numpy()[select(table)]))

    return {"one_run": lambda: float(np.nansum(field(np.array([args.row]), 0, nodes))),
            "one_node": lambda: float(np.nansum(field(np.arange(n), args.node, args.node + 1))),
            "region": lambda: float(np.nansum(field(np.arange(n), args.lo, args.hi))),
            "query": query}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=("run", "write", "measure"))
    ap.add_argument("study")
    ap.add_argument("work")
    ap.add_argument("result")
    ap.add_argument("--formats", nargs="+", choices=FORMATS, default=list(FORMATS))
    ap.add_argument("--format", choices=FORMATS)
    ap.add_argument("--field", default="pressure_coefficient")
    ap.add_argument("--scalar", default="axial_force_coefficient")
    ap.add_argument("--row", type=int, default=100)
    ap.add_argument("--node", type=int, default=3000)
    ap.add_argument("--region", default="0:672")
    ap.add_argument("--where", default="mach > 20 and alpha > 0")
    args = ap.parse_args()
    args.lo, args.hi = map(int, args.region.split(":"))
    out = path_of(args.work, args.format) if args.format else None
    if args.command == "write":
        d = load(args.study)
        # Exclude language/package import time for every writer.
        if args.format in ("exodus", "exodus_gzip", "cgns", "pmsh"):
            import pandas
        if args.format == "pmsh":
            import torch
            from physicsnemo.mesh import Mesh
        if args.format not in ("gamut_threads", "h5py"):
            if out.is_dir():
                shutil.rmtree(out)
            elif out.exists():
                out.unlink()
            start = time.perf_counter()
            if args.format == "gamut":
                write_gamut(d, str(out))
            else:
                write_native(d, out, args.format)
            elapsed = time.perf_counter() - start
        else:
            elapsed = None
        verify(d, out, args.format)
        print(json.dumps({"bytes": size_of(str(out)), "write_s": elapsed, "verified": True}))
    elif args.command == "measure":
        info = json.loads(Path(args.result).read_text())["shape"]
        reads = read_functions(args, args.format, out, info)
        # Imports and binding setup happen before timing, as in the original harness.
        for work in reads.values():
            work()
        print(json.dumps({name: {**timed(work), "checksum": work()} for name, work in reads.items()}))
    else:
        Path(args.work).mkdir(parents=True, exist_ok=True)
        d = load(args.study)
        info = {"runs": len(d["member"]), "nodes": len(d["points"][0]),
                "cells": len(d["cells"][0]), "geometries": len(d["points"]),
                "fields": list(d["fields"])}
        assert 0 <= args.row < info["runs"] and 0 <= args.node < info["nodes"]
        assert 0 <= args.lo < args.hi <= info["nodes"]
        result = {"case": Path(args.study).name, "machine": machine(), "shape": info,
                  "formats": {}, "reads": {k: getattr(args, k) for k in
                  ("field", "scalar", "row", "node", "region", "where")},
                  "native": {k: os.environ.get(k) for k in ("CGNS_LIBRARY", "CGNS_INDEX_BYTES",
                              "EXODUS_LIBRARY", "EXODUS_API_VERSION")}}
        for name in ("nvidia-physicsnemo", "tensordict", "torch"):
            try:
                result["machine"]["packages"][name] = metadata.version(name)
            except metadata.PackageNotFoundError:
                pass
        del d
        Path(args.result).write_text(json.dumps(result, indent=1))
        common = [args.study, args.work, args.result, "--field", args.field, "--scalar", args.scalar,
                  "--row", str(args.row), "--node", str(args.node), "--region", args.region,
                  "--where", args.where]
        for fmt in args.formats:
            written = run_child(__file__, "write", *common, "--format", fmt)
            measured = run_child(__file__, "measure", *common, "--format", fmt)
            result["formats"][fmt] = {**written, **measured}
            Path(args.result).write_text(json.dumps(result, indent=1))
            print(fmt, json.dumps(written), flush=True)
        for read in ("one_run", "one_node", "region", "query"):
            values = [r[read]["checksum"] for r in result["formats"].values()]
            np.testing.assert_allclose(values, values[0], rtol=1e-12, atol=1e-12)


if __name__ == "__main__":
    main()

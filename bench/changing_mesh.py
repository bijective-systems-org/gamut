"""A folder of VTK runs, each on its own mesh, against the same study as one
file.

    python bench/changing_mesh.py run FOLDER WORK_DIR RESULT.json
        [--field F] [--row R] [--where EXPR]

FOLDER holds one .vtu per run with parameters.csv and fields.csv, as
bench/airfrans.py writes it. The formats: the folder itself, the folder
zipped, one mestra file written by `mestra-vtk import`, and HDF5 written
with h5py, a group per run. (netCDF and Zarr have no standard layout for a
set of different meshes, so they are measured on one mesh only.) Each is
measured in a fresh process: opening, reading one run's points and field,
and choosing runs by condition. Each read opens and closes the file; times
are medians of five after a warm-up, with the file in the operating
system's cache.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import zipfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import machine, run_child, size_of, timed  # noqa: E402

FORMATS = ("vtk_folder", "vtk_zip", "mestra", "hdf5_per_run")
SKIP = ("vtkOriginalPointIds", "vtkOriginalCellIds", "cell_ids")


def path_of(folder: str, work: str, fmt: str) -> str:
    return folder if fmt == "vtk_folder" else os.path.join(
        work, {"vtk_zip": "vtk.zip", "mestra": "study.mes", "hdf5_per_run": "per_run.h5"}[fmt])


def runs_of(folder: str):
    import pandas as pd
    t = pd.read_csv(os.path.join(folder, "parameters.csv"), skiprows=[1, 2])
    return t


def write(fmt: str, folder: str, out: str) -> None:
    if fmt == "vtk_zip":
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for name in sorted(f for f in os.listdir(folder) if not f.startswith(".")):
                z.write(os.path.join(folder, name), name)
    elif fmt == "mestra":
        from mestra import vtk
        report = vtk.import_folder(folder, out, skip=SKIP)
        assert report["ok"], report
    elif fmt == "hdf5_per_run":
        import h5py
        import pyvista as pv
        from mestra.vtk import from_pyvista
        t = runs_of(folder)
        with h5py.File(out, "w") as f:
            for k, name in enumerate(t["file"]):
                run = from_pyvista(pv.read(os.path.join(folder, name)))
                g = f.create_group(f"runs/{k:05d}")
                g.create_dataset("points", data=run["points"], compression="gzip", compression_opts=4)
                for part, values in zip(("types", "offsets", "connectivity"), run["cells"]):
                    g.create_dataset(part, data=values, compression="gzip", compression_opts=4)
                for where in ("point_data", "cell_data"):
                    for key, values in run[where].items():
                        if key not in SKIP:
                            g.create_dataset(f"{where}/{key}", data=values, compression="gzip",
                                             compression_opts=4)
                for c in t.columns:
                    g.attrs[c] = t[c][k] if t[c].dtype.kind == "f" else str(t[c][k])


def readers(fmt: str, path: str, field: str, row: int, cond):
    ops = {">": np.greater, "<": np.less, ">=": np.greater_equal, "<=": np.less_equal}

    def mask(columns) -> np.ndarray:
        m = np.ones(len(columns[cond[0][0]]), dtype=bool)
        for c, op, v in cond:
            m &= ops[op](np.asarray(columns[c], dtype=float), v)
        return m

    if fmt == "vtk_folder":
        import pandas as pd
        import pyvista as pv

        def table():
            return pd.read_csv(os.path.join(path, "parameters.csv"), skiprows=[1, 2])

        def opened():
            return len(table())

        def one_run():
            name = table()["file"][row]
            m = pv.read(os.path.join(path, name))
            return float(m.points.sum() + m.point_data[field].sum())

        def query():
            return float(np.flatnonzero(mask(table())).sum())
        return opened, one_run, query

    if fmt == "mestra":
        import mestra
        expr = " and ".join(f"{c} {op} {v}" for c, op, v in cond)

        def opened():
            with mestra.open(path) as s:
                return s.row_count

        def one_run():
            with mestra.open(path) as s:
                return float(s.get_points(row=row).sum() + s.get_field(field, rows=row).sum())

        def query():
            with mestra.open(path) as s:
                return float(s.select(expr).sum())
        return opened, one_run, query

    if fmt == "hdf5_per_run":
        import h5py

        def opened():
            with h5py.File(path, "r") as f:
                return len(f["runs"])

        def one_run():
            with h5py.File(path, "r") as f:
                g = f[f"runs/{row:05d}"]
                return float(g["points"][()].sum() + g[f"point_data/{field}"][()].sum())

        def query():
            with h5py.File(path, "r") as f:
                runs = [f["runs"][k].attrs for k in f["runs"]]
                return float(np.flatnonzero(mask({c: [a[c] for a in runs] for c, _, _ in cond})).sum())
        return opened, one_run, query
    return None, None, None


def parse_where(text: str):
    return [(n, op, float(v)) for n, op, v in (part.split() for part in text.split(" and "))]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("command", choices=("run", "write", "measure"))
    ap.add_argument("folder")
    ap.add_argument("work")
    ap.add_argument("result", nargs="?")
    ap.add_argument("--format", choices=FORMATS)
    ap.add_argument("--field", default="p")
    ap.add_argument("--row", type=int, default=50)
    ap.add_argument("--where", default="inflow_speed > 50 and angle_of_attack > 5")
    args = ap.parse_args()
    out = path_of(args.folder, args.work, args.format) if args.format else None

    if args.command == "write":
        if args.format == "vtk_folder":
            print(json.dumps({"format": "vtk_folder", "write_s": None, "bytes": size_of(args.folder)}))
            return
        if os.path.exists(out):
            os.remove(out)
        for module in {"mestra": ["mestra", "mestra.vtk"], "hdf5_per_run": ["h5py", "pyvista"]}.get(
                args.format, []):
            __import__(module)
        start = time.perf_counter()
        write(args.format, args.folder, out)
        print(json.dumps({"format": args.format, "write_s": time.perf_counter() - start,
                          "bytes": size_of(out)}))
        return
    if args.command == "measure":
        reads = readers(args.format, out, args.field, args.row, parse_where(args.where))
        result: dict = {"format": args.format}
        for name, work in zip(("open", "one_run", "query"), reads):
            if work is not None:
                result[name] = timed(work)
                result[name]["checksum"] = work()
        print(json.dumps(result))
        return

    os.makedirs(args.work, exist_ok=True)
    me = os.path.abspath(__file__)
    t = runs_of(args.folder)
    results: dict = {"case": os.path.basename(os.path.normpath(args.folder)), "machine": machine(),
                     "reads": {"field": args.field, "row": args.row, "where": args.where},
                     "shape": {"runs": len(t)}, "formats": {}}
    for fmt in FORMATS:
        written = run_child(me, "write", args.folder, args.work, "--format", fmt)
        measured = run_child(me, "measure", args.folder, args.work, "--format", fmt,
                             "--field", args.field, "--row", str(args.row), "--where", args.where)
        results["formats"][fmt] = {**written, **measured}
        print(fmt, json.dumps({k: v.get("median_s", v) if isinstance(v, dict) else v
                               for k, v in results["formats"][fmt].items()}), flush=True)
    for read in ("one_run", "query"):
        sums = {f: r[read]["checksum"] for f, r in results["formats"].items() if read in r}
        first = next(iter(sums.values()))
        assert all(np.isclose(v, first, rtol=1e-9) for v in sums.values()), (read, sums)
    with open(args.result, "w") as fh:
        json.dump(results, fh, indent=1)


if __name__ == "__main__":
    main()

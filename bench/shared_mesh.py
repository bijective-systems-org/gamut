"""A study on one mesh, written as each format and read back the same ways.

    python bench/shared_mesh.py run STUDY.gamut WORK_DIR RESULT.json [--field F]
        [--node N] [--region A:B] [--where EXPR] [--scalar S]

STUDY.gamut is a Gamut file with a shared mesh (geometry fixed or per group).
Every format is written from the same arrays in memory, then each is
measured in a fresh process: reading one run's field, one node across every
run, a region of nodes across every run, a run-table query, and opening.
Each read opens and closes the file, as a script would; times are medians
of five after a warm-up, with the file in the operating system's cache.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import sys
import time
import zipfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import machine, run_child, size_of, timed  # noqa: E402

FORMATS = ("gamut", "gamut_threads", "vtk_folder", "vtk_zip", "vtkhdf", "hdf5_per_run", "netcdf",
           "zarr", "npz_per_run", "npy", "parquet")


# --- the study in memory -------------------------------------------------------------------


def load(path: str) -> dict:
    import gamut
    with gamut.open(path) as s:
        group = s.describe("coordinates").get("per", "fixed")
        table = s.table()
        fields = {n: s.get_field(n) for n in s.names("node_fields")}
        cells = s.get_cells()
        if group == "fixed":
            member = np.zeros(s.row_count, dtype=int)
            points = [s.get_points()]
        else:
            # One geometry per member of the group label, in first appearance.
            label = group[len("group:"):]
            names = list(dict.fromkeys(table[label].tolist()))
            member = np.array([names.index(x) for x in table[label]])
            points = [s.get_points(row=int(np.flatnonzero(member == m)[0])) for m in range(len(names))]
        declared = {n: s.describe(n) for n in list(table) + list(fields) + ["coordinates"]}
    return {"table": table, "fields": fields, "cells": cells, "points": points,
            "member": member, "declared": declared, "per": group}


# --- writers -------------------------------------------------------------------------------


def write_gamut(d: dict, out: str) -> None:
    import gamut
    labels = {n: {"role": d["declared"][n]["role"]} for n in d["table"]
              if d["declared"][n]["kind"] == "label"}
    parameters = {n: {"units": d["declared"][n]["units"], "role": d["declared"][n]["role"]}
                  for n in d["table"] if d["declared"][n]["kind"] == "parameter"}
    scalars = {n: d["declared"][n]["units"] for n in d["table"]
               if d["declared"][n]["kind"] == "scalar"}
    fields = {n: {"units": d["declared"][n]["units"], "at": "node"} for n in d["fields"]}
    fixed = d["per"] == "fixed"
    with gamut.create(out, writer="benchmark", mesh="shared", per=d["per"],
                       coordinates={"units": d["declared"]["coordinates"]["units"],
                                    "axes": d["points"][0].shape[1]},
                       parameters=parameters,
                       labels=labels, scalars=scalars, fields=fields) as study:
        study.set_mesh(d["points"][0] if fixed else None, d["cells"],
                       n_nodes=None if fixed else len(d["points"][0]))
        n = len(d["member"])
        for a in range(0, n, 256):
            rows = slice(a, min(n, a + 256))
            study.add_runs({k: v[rows] for k, v in d["table"].items()},
                           fields={k: v[rows] for k, v in d["fields"].items()},
                           points=None if fixed else [d["points"][m] for m in d["member"][rows]])


def write_vtk_folder(d: dict, out: str) -> None:
    import pyvista as pv
    os.makedirs(out)
    types, offsets, conn = d["cells"]
    legacy = np.insert(conn, offsets[:-1], np.diff(offsets))
    for k, m in enumerate(d["member"]):
        grid = pv.UnstructuredGrid(legacy, types, d["points"][m])
        for name, values in d["fields"].items():
            grid.point_data[name] = values[k]
        grid.save(os.path.join(out, f"run_{k:05d}.vtu"))
    with open(os.path.join(out, "parameters.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        names = list(d["table"])
        w.writerow(["file"] + names)
        for k in range(len(d["member"])):
            w.writerow([f"run_{k:05d}.vtu"] + [d["table"][n][k] for n in names])


def write_vtk_zip(d: dict, out: str, folder: str) -> None:
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name in sorted(f for f in os.listdir(folder) if not f.startswith(".")):
            z.write(os.path.join(folder, name), name)


def write_hdf5_per_run(d: dict, out: str) -> None:
    import h5py
    with h5py.File(out, "w") as f:
        types, offsets, conn = d["cells"]
        f["mesh/types"], f["mesh/offsets"], f["mesh/connectivity"] = types, offsets, conn
        for m, p in enumerate(d["points"]):
            f[f"mesh/points/{m}"] = p
        for k, m in enumerate(d["member"]):
            g = f.create_group(f"runs/{k:05d}")
            for name, values in d["fields"].items():
                g.create_dataset(name, data=values[k], compression="gzip", compression_opts=4, shuffle=True)
            for name, column in d["table"].items():
                v = column[k]
                g.attrs[name] = v if isinstance(v, (float, np.floating)) else str(v)
            g.attrs["member"] = int(m)


def write_vtkhdf(d: dict, out: str) -> None:
    """VTKHDF 2.2, an UnstructuredGrid with one time step per run: each shape's
    points stored once, and step offsets pointing every run at its shape's
    points and at its own slice of each field. Fields are chunked a step at a
    time and compressed as the other HDF5 copies are; the run table's number
    columns are FieldData, one value per step; geometry is stored plain."""
    import h5py
    types, offsets, conn = d["cells"]
    n_runs, n_nodes, n_shapes = len(d["member"]), len(d["points"][0]), len(d["points"])
    with h5py.File(out, "w") as f:
        g = f.create_group("VTKHDF")
        g.attrs["Version"] = np.array([2, 2], dtype="i8")
        kind = "UnstructuredGrid".encode("ascii")
        g.attrs.create("Type", kind, dtype=h5py.string_dtype("ascii", len(kind)))
        g["NumberOfPoints"] = np.full(n_shapes, n_nodes, dtype="i8")
        g["NumberOfCells"] = np.full(n_shapes, len(types), dtype="i8")
        g["NumberOfConnectivityIds"] = np.full(n_shapes, len(conn), dtype="i8")
        g["Points"] = np.concatenate(d["points"])
        g["Types"] = np.tile(types, n_shapes)
        g["Offsets"] = np.tile(offsets, n_shapes)
        g["Connectivity"] = np.tile(conn, n_shapes)
        pd_ = g.create_group("PointData")
        for name, values in d["fields"].items():
            pd_.create_dataset(name, data=values.reshape(-1), chunks=(n_nodes,),
                               compression="gzip", compression_opts=4, shuffle=True)
        fd = g.create_group("FieldData")
        for name, column in d["table"].items():
            if column.dtype.kind == "f":
                fd.create_dataset(name, data=column.reshape(-1, 1))
        s = g.create_group("Steps")
        s.attrs["NSteps"] = n_runs
        s["Values"] = np.arange(n_runs, dtype="f8")
        s["PartOffsets"] = d["member"].astype("i8")
        s["NumberOfParts"] = np.ones(n_runs, dtype="i8")
        s["PointOffsets"] = d["member"].astype("i8") * n_nodes
        s["CellOffsets"] = d["member"].astype("i8")[:, None] * len(types)
        s["ConnectivityIdOffsets"] = d["member"].astype("i8")[:, None] * len(conn)
        po = s.create_group("PointDataOffsets")
        for name in d["fields"]:
            po[name] = np.arange(n_runs, dtype="i8") * n_nodes
        fo = s.create_group("FieldDataOffsets")
        for name in fd:
            fo[name] = np.arange(n_runs, dtype="i8")


def write_npz_per_run(d: dict, out: str) -> None:
    """A compressed NumPy file per run, its fields and points, beside a CSV of
    the run table: the layout many training pipelines start from."""
    os.makedirs(out)
    for k, m in enumerate(d["member"]):
        np.savez_compressed(os.path.join(out, f"run_{k:05d}.npz"), points=d["points"][m],
                            **{name: values[k] for name, values in d["fields"].items()})
    with open(os.path.join(out, "parameters.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        names = list(d["table"])
        w.writerow(["file"] + names)
        for k in range(len(d["member"])):
            w.writerow([f"run_{k:05d}.npz"] + [d["table"][n][k] for n in names])


def write_npy(d: dict, out: str) -> None:
    """One uncompressed .npy per field (runs x nodes), read memory-mapped, and
    the run table as CSV: no compression, units or mesh, as fast as a disk read."""
    os.makedirs(out)
    for name, values in d["fields"].items():
        np.save(os.path.join(out, f"{name}.npy"), np.ascontiguousarray(values))
    np.save(os.path.join(out, "points.npy"), np.stack(d["points"]))
    np.save(os.path.join(out, "member.npy"), d["member"])
    with open(os.path.join(out, "parameters.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        names = list(d["table"])
        w.writerow(names)
        for k in range(len(d["member"])):
            w.writerow([d["table"][n][k] for n in names])


def dataset(d: dict):
    import xarray as xr
    variables = {n: (("run", "node"), v) for n, v in d["fields"].items()}
    for n, v in d["table"].items():
        variables[n] = (("run",), v.astype(str) if v.dtype.kind in "OU" else v)
    variables["points"] = (("member", "node", "axis"), np.stack(d["points"]))
    variables["member_of_run"] = (("run",), d["member"])
    return xr.Dataset(variables)


def write_netcdf(d: dict, out: str) -> None:
    ds = dataset(d)
    encoding = {n: {"zlib": True, "complevel": 4} for n in ds.data_vars if ds[n].dtype.kind == "f"}
    ds.to_netcdf(out, engine="netcdf4", encoding=encoding)


def write_zarr(d: dict, out: str) -> None:
    dataset(d).to_zarr(out, mode="w", consolidated=True)


def write_parquet(d: dict, out: str) -> None:
    import pandas as pd
    pd.DataFrame(d["table"]).to_parquet(out)


# --- readers: (open and list, one run, one node, a region, query) -------------------------


def readers(fmt: str, path: str, field: str, where: dict, scalar: str):
    """The five reads for one format, each a function returning a checksum."""
    lo, hi, node, row = where["lo"], where["hi"], where["node"], where["row"]
    cond = where["cond"]                         # [(column, op, value)]

    def mask(columns) -> np.ndarray:
        ops = {">": np.greater, "<": np.less, ">=": np.greater_equal, "<=": np.less_equal}
        m = np.ones(len(columns[cond[0][0]]), dtype=bool)
        for c, op, v in cond:
            m &= ops[op](np.asarray(columns[c], dtype=float), v)
        return m

    if fmt in ("gamut", "gamut_threads"):
        import gamut
        expr = " and ".join(f"{c} {op} {v}" for c, op, v in cond)
        threads = 4 if fmt == "gamut_threads" else 1

        def opened():
            with gamut.open(path, threads=threads) as s:
                return len(s.names("node_fields")) + s.row_count

        def one_run():
            with gamut.open(path, threads=threads) as s:
                return float(s.get_field(field, rows=row).sum())

        def one_node():
            with gamut.open(path, threads=threads) as s:
                return float(s.get_field(field, nodes=[node]).sum())

        def region():
            with gamut.open(path, threads=threads) as s:
                return float(s.get_field(field, nodes=slice(lo, hi)).sum())

        def query():
            with gamut.open(path, threads=threads) as s:
                return float(np.nansum(s.get_scalar(scalar, rows=s.select(expr))))
        return opened, one_run, one_node, region, query

    if fmt == "vtk_folder":
        import pandas as pd
        import pyvista as pv
        files = sorted(f for f in os.listdir(path) if f.endswith(".vtu") and not f.startswith("."))

        def opened():
            return len(files) + len(pd.read_csv(os.path.join(path, "parameters.csv")))

        def one_run():
            return float(pv.read(os.path.join(path, files[row])).point_data[field].sum())

        def one_node():
            return float(sum(pv.read(os.path.join(path, f)).point_data[field][node] for f in files))

        def region():
            return float(sum(pv.read(os.path.join(path, f)).point_data[field][lo:hi].sum()
                             for f in files))

        def query():
            t = pd.read_csv(os.path.join(path, "parameters.csv"))
            return float(np.nansum(t[scalar].to_numpy()[mask(t)]))
        return opened, one_run, one_node, region, query

    if fmt == "vtkhdf":
        import h5py

        def opened():
            with h5py.File(path, "r") as f:
                return int(f["VTKHDF/Steps"].attrs["NSteps"]) + len(f["VTKHDF/PointData"])

        def one_run():
            with h5py.File(path, "r") as f:
                start = int(f["VTKHDF/Steps/PointDataOffsets"][field][row])
                n = int(f["VTKHDF/NumberOfPoints"][0])
                return float(f["VTKHDF/PointData"][field][start:start + n].sum())

        # Every step's slice is the same length here, so a node across steps is
        # one strided read; each chunk holds one step, so either read touches
        # every chunk once.
        def one_node():
            with h5py.File(path, "r") as f:
                n = int(f["VTKHDF/NumberOfPoints"][0])
                return float(f["VTKHDF/PointData"][field][node::n].sum())

        def region():
            with h5py.File(path, "r") as f:
                n = int(f["VTKHDF/NumberOfPoints"][0])
                return float(f["VTKHDF/PointData"][field][()].reshape(-1, n)[:, lo:hi].sum())

        def query():
            with h5py.File(path, "r") as f:
                fd = f["VTKHDF/FieldData"]
                columns = {c: fd[c][:, 0] for c, _, _ in cond}
                return float(np.nansum(fd[scalar][:, 0][mask(columns)]))
        return opened, one_run, one_node, region, query

    if fmt in ("npz_per_run", "npy"):
        import pandas as pd
        def runs():
            return sorted(f for f in os.listdir(path) if f.endswith(".npz")) if fmt == "npz_per_run" else []

        def table():
            return pd.read_csv(os.path.join(path, "parameters.csv"))

        def block():
            return np.load(os.path.join(path, f"{field}.npy"), mmap_mode="r")

        def opened():
            files = runs()
            return len(table()) + (len(files) if files else block().shape[0])

        def one_run():
            files = runs()
            if files:
                with np.load(os.path.join(path, files[row])) as z:
                    return float(z[field].sum())
            return float(np.asarray(block()[row]).sum())

        def one_node():
            files = runs()
            if files:
                total = 0.0
                for name in files:
                    with np.load(os.path.join(path, name)) as z:
                        total += float(z[field][node])
                return total
            return float(np.asarray(block()[:, node]).sum())

        def region():
            files = runs()
            if files:
                total = 0.0
                for name in files:
                    with np.load(os.path.join(path, name)) as z:
                        total += float(z[field][lo:hi].sum())
                return total
            return float(np.asarray(block()[:, lo:hi]).sum())

        def query():
            t = table()
            return float(np.nansum(t[scalar].to_numpy()[mask(t)]))
        return opened, one_run, one_node, region, query

    if fmt == "hdf5_per_run":
        import h5py

        def opened():
            with h5py.File(path, "r") as f:
                return len(f["runs"])

        def one_run():
            with h5py.File(path, "r") as f:
                return float(f[f"runs/{row:05d}/{field}"][()].sum())

        def one_node():
            with h5py.File(path, "r") as f:
                return float(sum(f[f"runs/{k}/{field}"][node] for k in f["runs"]))

        def region():
            with h5py.File(path, "r") as f:
                return float(sum(f[f"runs/{k}/{field}"][lo:hi].sum() for k in f["runs"]))

        def query():
            with h5py.File(path, "r") as f:
                runs = [f["runs"][k].attrs for k in f["runs"]]
                columns = {c: [a[c] for a in runs] for c, _, _ in cond}
                values = np.array([a[scalar] for a in runs], dtype=float)
                return float(np.nansum(values[mask(columns)]))
        return opened, one_run, one_node, region, query

    if fmt in ("netcdf", "zarr"):
        import xarray as xr

        def open_ds():
            return xr.open_dataset(path, engine="netcdf4") if fmt == "netcdf" else \
                xr.open_zarr(path, consolidated=True)

        def opened():
            with open_ds() as ds:
                return len(ds.data_vars) + ds.sizes["run"]

        def one_run():
            with open_ds() as ds:
                return float(ds[field].isel(run=row).values.sum())

        def one_node():
            with open_ds() as ds:
                return float(ds[field].isel(node=node).values.sum())

        def region():
            with open_ds() as ds:
                return float(ds[field].isel(node=slice(lo, hi)).values.sum())

        def query():
            with open_ds() as ds:
                columns = {c: ds[c].values for c, _, _ in cond}
                return float(np.nansum(ds[scalar].values[mask(columns)]))
        return opened, one_run, one_node, region, query

    if fmt == "parquet":
        import pandas as pd

        def query():
            t = pd.read_parquet(path)
            return float(np.nansum(t[scalar].to_numpy()[mask(t)]))
        return None, None, None, None, query
    return None, None, None, None, None


# --- the commands ---------------------------------------------------------------------------


def parse_where(text: str) -> list[tuple[str, str, float]]:
    out = []
    for part in text.split(" and "):
        name, op, value = part.split()
        out.append((name, op, float(value)))
    return out


def path_of(work: str, fmt: str) -> str:
    return os.path.join(work, {"gamut": "study.gamut", "gamut_threads": "study.gamut",
                               "vtk_folder": "vtk", "vtk_zip": "vtk.zip", "vtkhdf": "study.vtkhdf",
                               "npz_per_run": "npz", "npy": "npy",
                               "hdf5_per_run": "per_run.h5", "netcdf": "study.nc",
                               "zarr": "study.zarr", "parquet": "table.parquet"}[fmt])


def cmd_write(args) -> dict:
    out = path_of(args.work, args.format)
    if args.format == "gamut_threads":
        # The same file as "gamut", read with four decompression threads.
        return {"format": args.format, "write_s": None, "bytes": size_of(out)}
    d = load(args.study)
    if os.path.isdir(out):
        shutil.rmtree(out)
    elif os.path.exists(out):
        os.remove(out)
    writers = {"gamut": write_gamut, "vtk_folder": write_vtk_folder, "hdf5_per_run":
               write_hdf5_per_run, "netcdf": write_netcdf, "zarr": write_zarr,
               "parquet": write_parquet, "vtkhdf": write_vtkhdf, "npz_per_run": write_npz_per_run,
               "npy": write_npy}
    # Libraries are imported before the clock starts: a write is timed, not
    # an import.
    for module in {"gamut": ["gamut"], "vtk_folder": ["pyvista"], "hdf5_per_run": ["h5py"],
                   "vtkhdf": ["h5py"],
                   "netcdf": ["xarray", "netCDF4"], "zarr": ["xarray", "zarr"],
                   "parquet": ["pandas", "pyarrow"]}.get(args.format, []):
        __import__(module)
    start = time.perf_counter()
    if args.format == "vtk_zip":
        write_vtk_zip(d, out, path_of(args.work, "vtk_folder"))
    else:
        writers[args.format](d, out)
    return {"format": args.format, "write_s": time.perf_counter() - start, "bytes": size_of(out)}


def cmd_measure(args) -> dict:
    where = {"row": args.row, "node": args.node, "lo": args.lo, "hi": args.hi,
             "cond": parse_where(args.where)}
    reads = readers(args.format, path_of(args.work, args.format), args.field, where, args.scalar)
    out: dict = {"format": args.format}
    for name, work in zip(("open", "one_run", "one_node", "region", "query"), reads):
        if work is not None:
            result = timed(work)
            result["checksum"] = work()
            out[name] = result
    return out


def cmd_run(args) -> None:
    os.makedirs(args.work, exist_ok=True)
    me = os.path.abspath(__file__)
    common = ["--field", args.field, "--row", str(args.row), "--node", str(args.node),
              "--region", f"{args.lo}:{args.hi}", "--where", args.where, "--scalar", args.scalar]
    results: dict = {"case": os.path.basename(args.study), "machine": machine(), "formats": {},
                     "reads": {"field": args.field, "row": args.row, "node": args.node,
                               "region": [args.lo, args.hi], "where": args.where,
                               "scalar": args.scalar}}
    d = load(args.study)
    results["shape"] = {"runs": len(d["member"]), "nodes": len(d["points"][0]),
                        "cells": len(d["cells"][0]), "geometries": len(d["points"]),
                        "fields": sorted(d["fields"])}
    del d
    for fmt in FORMATS:
        written = run_child(me, "write", args.study, args.work, "--format", fmt)
        measured = run_child(me, "measure", args.study, args.work, "--format", fmt, *common)
        results["formats"][fmt] = {**written, **measured}
        print(fmt, json.dumps({k: v.get("median_s", v) if isinstance(v, dict) else v
                               for k, v in results["formats"][fmt].items()}), flush=True)
    # Every format read the same numbers.
    for read in ("one_run", "one_node", "region", "query"):
        sums = {f: r[read]["checksum"] for f, r in results["formats"].items() if read in r}
        first = next(iter(sums.values()))
        assert all(np.isclose(v, first, rtol=1e-9) for v in sums.values()), (read, sums)
    with open(args.result, "w") as fh:
        json.dump(results, fh, indent=1)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("command", choices=("run", "write", "measure"))
    ap.add_argument("study")
    ap.add_argument("work")
    ap.add_argument("result", nargs="?")
    ap.add_argument("--format", choices=FORMATS)
    ap.add_argument("--field", default="pressure_coefficient")
    ap.add_argument("--row", type=int, default=100)
    ap.add_argument("--node", type=int, default=3000)
    ap.add_argument("--region", default="0:672")
    ap.add_argument("--where", default="mach > 20 and alpha > 0")
    ap.add_argument("--scalar", default="axial_force_coefficient")
    args = ap.parse_args()
    args.lo, args.hi = (int(x) for x in args.region.split(":"))
    if args.command == "run":
        cmd_run(args)
    else:
        print(json.dumps(cmd_write(args) if args.command == "write" else cmd_measure(args)))


if __name__ == "__main__":
    main()

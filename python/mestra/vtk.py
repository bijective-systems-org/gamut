"""VTK in and out of mestra files, on PyVista and pandas (the `vtk` extra:
`pip install mestra[vtk]`).

    mestra-vtk import RUNS_DIR [-o study.mes] [--parameters CSV]
                      [--fields CSV] [--skip a,b] [--round-bits N] [--json]
    mestra-vtk export study.mes OUT_DIR [--json]

(or `python -m mestra.vtk ...`).

`import` turns a folder of VTK runs (one .vtu, .vtp or legacy .vtk file per
run) into one study file. It needs two small tables beside
the runs; on the first call it writes them as templates and stops:

  parameters.csv   one line per run: the file, then each parameter or label

      file,mach,alpha,config
      units,1,degree,
      role,condition,condition,categorical      (optional line)
      run_000.vtu,0.6,2.0,clean

  fields.csv       the units of every array, and of the coordinates

      name,units
      coordinates,m
      p,Pa
      U,m s-1

A number column is a parameter (float64), a text column a label; the role
line can say otherwise. A parameter with role `time` and one `group` label
make a set of transients. Arrays of three components become vectors
(`U_x`, `U_y`, `U_z` with `vector = U`); integer arrays become mesh labels
(on one mesh, the same in every run). Runs with the same cells share one
mesh, its geometry stored once if it never moves and per run otherwise;
runs with different cells keep a mesh each (a changing mesh).

`export` writes one .vtu per run back, with parameters.csv and fields.csv,
so a study round-trips and nothing is locked in.

Exit status: 0 done, 1 refused (every problem listed), 2 templates written
and waiting to be filled in. `--json` prints the same report as JSON.

The rest of the package never imports PyVista: `to_pyvista` and
`from_pyvista` here are the bridge, and this module is also a worked
example for anyone writing a converter for another format.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from typing import Any

import numpy as np
import pandas as pd
import pyvista as pv

import mestra

VTK_SUFFIXES = (".vtu", ".vtp", ".vtk")
PARAMETER_ROLES = {"design", "condition", "time"}
LABEL_ROLES = {"group", "categorical", "status", "split"}
AXES = ("x", "y", "z")


class Problems(Exception):
    """What stops an import or export, every problem found at once."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = problems


# --- the PyVista bridge -----------------------------------------------------------------


# VTK's axis-aligned cells, from image data and rectilinear grids, are a
# hexahedron and a quadrilateral with nodes in another order.
REORDER = {11: (12, (0, 1, 3, 2, 4, 5, 7, 6)),   # voxel -> hexahedron
           8: (9, (0, 1, 3, 2))}                  # pixel -> quadrilateral
SPEC_CELLS = {1, 3, 5, 7, 9, 10, 12, 13, 14, 21, 22, 23, 24, 25, 26, 27}


def from_pyvista(mesh: Any) -> dict[str, Any]:
    """A PyVista mesh as plain arrays: points, cells (types, offsets,
    connectivity) in the spec's cell types, and its point and cell arrays.
    Voxels and pixels become hexahedra and quadrilaterals."""
    grid = mesh if isinstance(mesh, pv.UnstructuredGrid) else mesh.cast_to_unstructured_grid()
    types = np.array(grid.celltypes, dtype=np.uint8)
    offsets = np.asarray(grid.cell_offsets if hasattr(grid, "cell_offsets") else grid.offset,
                         dtype=np.int64)
    connectivity = np.array(grid.cell_connectivity, dtype=np.int64)
    converted = []
    for vtk_type, (spec_type, order) in REORDER.items():
        cells = np.flatnonzero(types == vtk_type)
        if cells.size:
            starts = offsets[cells][:, None] + np.arange(len(order))
            connectivity[starts] = connectivity[starts][:, list(order)]
            types[cells] = spec_type
            converted.append(vtk_type)
    return {"points": np.asarray(grid.points), "converted": converted,
            "cells": (types, offsets, connectivity),
            "point_data": {k: np.asarray(grid.point_data[k]) for k in grid.point_data.keys()},
            "cell_data": {k: np.asarray(grid.cell_data[k]) for k in grid.cell_data.keys()}}


def to_pyvista(study: mestra.Study, row: int) -> pv.UnstructuredGrid:
    """One row of a study file as a PyVista grid: its geometry, every field
    (vector components joined back into one array) and the mesh labels."""
    fixed = study.describe("coordinates").get("per", "fixed") == "fixed"
    points = study.get_points() if fixed else study.get_points(row=row)
    types, offsets, connectivity = study.get_cells(row=row) if study.type == "changing" \
        else study.get_cells()
    counts = np.diff(offsets)
    legacy = np.insert(connectivity, offsets[:-1], counts)
    grid = pv.UnstructuredGrid(legacy, types, np.asarray(points, dtype=np.float64)
                               if points.shape[1] == 3 else _pad3(points))
    for where, data in (("node", grid.point_data), ("cell", grid.cell_data)):
        vectors: dict[str, dict[str, np.ndarray]] = {}
        for name in study.names(f"{where}_fields"):
            d = study.describe(name)
            values = study.get_field(name, rows=row)
            if d.get("vector") and d.get("axis") in AXES:
                vectors.setdefault(d["vector"], {})[d["axis"]] = values
            else:
                data[name] = values
        for vector, parts in vectors.items():
            data[vector] = np.stack([parts[a] for a in AXES if a in parts], axis=1)
        for name in study.names(f"{where}_labels"):
            data[name] = study.get_mesh_label(name, row=row if study.type == "changing" else None)
    return grid


def _pad3(points: np.ndarray) -> np.ndarray:
    out = np.zeros((points.shape[0], 3))
    out[:, :points.shape[1]] = points
    return out


# --- the two tables ---------------------------------------------------------------------


def read_parameters(path: str) -> tuple[pd.DataFrame, dict[str, str], dict[str, str], list[str]]:
    """The parameters CSV: its runs, each column's units and role, and the
    problems found (all of them, each naming its line and column)."""
    problems: list[str] = []
    try:
        raw = pd.read_csv(path, header=None, dtype=str, keep_default_na=False)
    except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError) as e:
        return pd.DataFrame(), {}, {}, [f"{path}: not a readable CSV table ({e})"]
    if raw.shape[0] < 2 or raw.iloc[0, 0].strip() != "file" or raw.iloc[1, 0].strip() != "units":
        return pd.DataFrame(), {}, {}, [f"{path}: line 1 starts with `file` and line 2 with "
                                        "`units`"]
    columns = [c.strip() for c in raw.iloc[0]]
    units = {c: raw.iloc[1, j].strip() for j, c in enumerate(columns)}
    first = 2
    roles: dict[str, str] = {}
    if raw.shape[0] > 2 and raw.iloc[2, 0].strip() == "role":
        roles = {c: raw.iloc[2, j].strip() for j, c in enumerate(columns) if raw.iloc[2, j].strip()}
        first = 3
    runs = raw.iloc[first:].reset_index(drop=True)
    runs.columns = columns
    if len(set(columns)) != len(columns):
        problems.append(f"{path}: a column name appears twice")
    for j, c in enumerate(columns):
        for i, v in enumerate(runs[c]):
            if v.strip() == "":
                problems.append(f"{path}: line {first + i + 1}, column {c}: blank")
    return runs, units, roles, problems


def read_fields(path: str) -> dict[str, str]:
    try:
        table = pd.read_csv(path, dtype=str, keep_default_na=False)
    except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError) as e:
        raise Problems([f"{path}: not a readable CSV table ({e})"]) from None
    if list(table.columns[:2]) != ["name", "units"]:
        raise Problems([f"{path}: the header is `name,units`"])
    return {n.strip(): u.strip() for n, u in zip(table["name"], table["units"])}


def write_templates(folder: str, files: list[str], arrays: list[str]) -> list[str]:
    written = []
    p = os.path.join(folder, "parameters.csv")
    if not os.path.exists(p):
        with open(p, "w") as fh:
            fh.write("file\nunits\n" + "".join(f"{f}\n" for f in files))
        written.append(p)
    q = os.path.join(folder, "fields.csv")
    if not os.path.exists(q):
        with open(q, "w") as fh:
            fh.write("name,units\ncoordinates,\n" + "".join(f"{a},\n" for a in arrays))
        written.append(q)
    return written


# --- import -------------------------------------------------------------------------------


def import_folder(folder: str, out: str, parameters: str | None = None,
                  fields: str | None = None, skip: tuple[str, ...] = (),
                  round_bits: int | None = None) -> dict[str, Any]:
    """Imports a folder of VTK runs; returns a report. Raises Problems
    with every problem found before anything is written."""
    # Hidden files are not runs: macOS writes "._name.vtu" beside each file
    # on drives it cannot keep its metadata on.
    found = sorted(f for f in os.listdir(folder)
                   if f.lower().endswith(VTK_SUFFIXES) and not f.startswith("."))
    parameters = parameters or os.path.join(folder, "parameters.csv")
    fields = fields or os.path.join(folder, "fields.csv")
    if not os.path.exists(parameters) or not os.path.exists(fields):
        if not found:
            raise Problems([f"{folder}: no .vtu, .vtp or .vtk files"])
        first = from_pyvista(pv.read(os.path.join(folder, found[0])))
        data = {**first["point_data"], **first["cell_data"]}
        # Float arrays need units; integer arrays become mesh labels.
        arrays = sorted(k for k, v in data.items() if v.dtype.kind == "f" and k not in skip)
        written = write_templates(folder, found, arrays)
        return {"ok": False, "templates": written,
                "next": "fill in the units (and parameter values), then run import again"}

    runs, units, roles, problems = read_parameters(parameters)
    base = os.path.dirname(os.path.abspath(parameters))
    files = list(runs["file"]) if "file" in runs else []
    missing = [f for f in files if not os.path.exists(os.path.join(base, f))]
    problems += [f"{parameters}: {f} does not exist" for f in missing]
    left_out = sorted(set(found) - {os.path.basename(f) for f in files})
    field_units = read_fields(fields)

    # Columns: parameters (numbers) and labels (text), unless a role says.
    param_cols, label_cols = {}, {}
    for c in runs.columns[1:] if len(runs.columns) else []:
        role = roles.get(c, "")
        given = runs[c][runs[c].str.strip() != ""]          # blanks are reported above
        numeric = len(given) > 0 and pd.to_numeric(given, errors="coerce").notna().all()
        if role in LABEL_ROLES or (not role and not numeric):
            if units.get(c):
                problems.append(f"{parameters}: column {c} is a label and takes no units")
            label_cols[c] = role or "categorical"
        elif role in PARAMETER_ROLES or (not role and numeric):
            if not numeric:
                problems.append(f"{parameters}: column {c} has role {role} but holds text")
            if not units.get(c):
                problems.append(f"{parameters}: column {c} needs units (`1` when dimensionless)")
            param_cols[c] = role or "design"
        else:
            problems.append(f"{parameters}: column {c}: role {role!r} is none of "
                            f"{sorted(PARAMETER_ROLES | LABEL_ROLES)}")
    groups = [c for c, r in label_cols.items() if r == "group"]
    times = [c for c, r in param_cols.items() if r == "time"]
    if times and len(groups) != 1:
        problems.append(f"{parameters}: a time column needs exactly one group column (the run "
                        f"each step belongs to); found {len(groups)}")
    if problems:
        raise Problems(problems)

    # First pass: the same arrays everywhere; one mesh or a mesh per run;
    # is the geometry fixed?
    first = from_pyvista(pv.read(os.path.join(base, files[0])))
    types0, offsets0, conn0 = first["cells"]
    if (types0 == 42).any():
        problems.append(f"{files[0]}: polyhedra (VTK 42) are not in version 1; export "
                        "decomposed cells (foamToVTK -poly-decomp)")
    other = sorted(set(int(t) for t in np.unique(types0)) - SPEC_CELLS - {42})
    if other:
        problems.append(f"{files[0]}: VTK cell types {other} are not in version 1 (spec section "
                        "15); triangulate strips and split poly-lines first (PyVista "
                        "triangulate())")
    arrays = {("node", k): v for k, v in first["point_data"].items() if k not in skip}
    arrays.update({("cell", k): v for k, v in first["cell_data"].items() if k not in skip})
    labels_fixed = {key: True for key, v in arrays.items() if v.dtype.kind in "iu"}
    fixed_geometry = True
    one_mesh = True          # the same cells in every run; otherwise a mesh per run
    for f in files[1:]:
        run = from_pyvista(pv.read(os.path.join(base, f)))
        t, o, c = run["cells"]
        other = sorted(set(int(x) for x in np.unique(t)) - SPEC_CELLS)
        if other:
            problems.append(f"{f}: VTK cell types {other} are not in version 1")
        if one_mesh and not (np.array_equal(t, types0) and np.array_equal(o, offsets0)
                             and np.array_equal(c, conn0)):
            one_mesh = False
        if one_mesh and not np.array_equal(run["points"], first["points"]):
            fixed_geometry = False
        here = {("node", k): v for k, v in run["point_data"].items() if k not in skip}
        here.update({("cell", k): v for k, v in run["cell_data"].items() if k not in skip})
        if set(here) != set(arrays):
            problems.append(f"{f}: its arrays {sorted(k for _, k in here)} differ from "
                            f"{files[0]}'s {sorted(k for _, k in arrays)}")
            continue
        for key, v in here.items():
            if v.shape[1:] != arrays[key].shape[1:] or v.dtype.kind != arrays[key].dtype.kind:
                problems.append(f"{f}: array {key[1]} has other components or another type")
            elif one_mesh and v.shape != arrays[key].shape:
                problems.append(f"{f}: array {key[1]} has another length")
            elif key in labels_fixed and not (v.shape == arrays[key].shape
                                              and np.array_equal(v, arrays[key])):
                labels_fixed[key] = False
    if not one_mesh:
        # Each run keeps its own mesh, and its integer arrays as its own mesh
        # labels; nothing claims node k of one run is node k of another.
        fixed_geometry = False
        labels_fixed = {key: True for key in labels_fixed}
    # Declarations from the first run's arrays.
    field_decl: dict[str, dict] = {}
    mesh_labels: dict[str, dict] = {}
    label_source: dict[str, tuple[str, str]] = {}
    split: dict[tuple[str, str], list[str]] = {}
    origin: dict[str, str] = {}          # stored name -> the VTK array it comes from
    notes: list[str] = []

    def claim(stored: str, where: str, name: str) -> None:
        # Names are unique in a file: two arrays giving one name is refused.
        what = f"the {where} array {name}"
        if stored in origin:
            problems.append(f"{what} and {origin[stored]} both give the name {stored}; rename "
                            "one, or --skip it")
        origin[stored] = what
    for vtk_type, word in ((11, "voxels stored as hexahedra"), (8, "pixels stored as "
                                                                   "quadrilaterals")):
        if vtk_type in first["converted"]:
            notes.append(word)
    for (where, name), v in sorted(arrays.items()):
        # A cell array named like a point array (foamToVTK writes both) is
        # kept as <name>_cell.
        stored = name
        if where == "cell" and ("node", name) in arrays:
            stored = f"{name}_cell"
            notes.append(f"the cell array {name} is stored as {stored} beside the point array "
                         f"{name}")
        if v.dtype.kind in "iu":
            if not labels_fixed[(where, name)]:
                problems.append(f"array {name}: integers that change between runs; give them as "
                                "floats, or --skip it")
            claim(stored, where, name)
            mesh_labels[stored] = {"at": where}
            label_source[stored] = (where, name)
            continue
        if v.dtype.kind != "f":
            problems.append(f"array {name}: {v.dtype} arrays are not imported; --skip it")
            continue
        u = field_units.get(name, "")
        if not u:
            problems.append(f"array {name}: no units in {fields} (`1` when dimensionless), or "
                            "--skip it")
            continue
        components = 1 if v.ndim == 1 else v.shape[1]
        spec: dict[str, Any] = {"units": u, "at": where}
        if round_bits is not None:
            spec["round_bits"] = round_bits
        if components == 1:
            claim(stored, where, name)
            field_decl[stored] = spec
            split[(where, name)] = [stored]
        elif components in (2, 3):
            parts = [f"{stored}_{a}" for a in AXES[:components]]
            for part, axis in zip(parts, AXES):
                claim(part, where, name)
                field_decl[part] = dict(spec, vector=stored, axis=axis)
            split[(where, name)] = parts
        else:
            parts = [f"{stored}_{i}" for i in range(components)]
            for part in parts:
                claim(part, where, name)
                field_decl[part] = dict(spec)
            split[(where, name)] = parts
            notes.append(f"array {name}: {components} components, stored as {', '.join(parts)} "
                         "(tensors are not declared in version 1)")
    taken = set(param_cols) | set(label_cols) | {"file"} | set(mesh_labels)
    for name in field_decl:
        if name in taken:
            problems.append(f"the name {name} is used twice (a column and an array)")
    coordinate_units = field_units.get("coordinates", "")
    if not coordinate_units:
        problems.append(f"{fields}: give the units of the coordinates (a `coordinates` line)")
    if problems:
        raise Problems(problems)

    # Second pass: write, one run at a time.
    label_spec = {c: {"role": r} for c, r in label_cols.items()}
    label_spec["file"] = {"role": "categorical"}
    param_spec = {c: {"units": units[c], "role": r} for c, r in param_cols.items()}
    if times:
        for t in times:
            param_spec[t]["run_group"] = groups[0]
    try:
        with mestra.create(out, writer="mestra-vtk", parameters=param_spec, labels=label_spec,
                           fields=field_decl, mesh_labels=mesh_labels,
                           mesh="shared" if one_mesh else "changing",
                           per="fixed" if fixed_geometry else "run",
                           coordinates={"units": coordinate_units, "axes": 3}) as study:
            if one_mesh:
                study.set_mesh(first["points"] if fixed_geometry else None, first["cells"],
                               labels={k: arrays[label_source[k]] for k in mesh_labels},
                               n_nodes=None if fixed_geometry else len(first["points"]))
            for i, f in enumerate(files):
                run = first if i == 0 else from_pyvista(pv.read(os.path.join(base, f)))
                values: dict[str, Any] = {"file": f}
                for c in param_cols:
                    values[c] = float(runs[c][i])
                for c in label_cols:
                    values[c] = runs[c][i]
                data: dict[str, np.ndarray] = {}
                for (where, name), parts in split.items():
                    v = run["point_data" if where == "node" else "cell_data"][name]
                    if len(parts) == 1:
                        data[parts[0]] = v
                    else:
                        for k, part in enumerate(parts):
                            data[part] = np.ascontiguousarray(v[:, k])
                if one_mesh:
                    study.add_run(values, fields=data,
                                  points=None if fixed_geometry else run["points"])
                else:
                    own = {k: run["point_data" if label_source[k][0] == "node" else "cell_data"]
                           [label_source[k][1]] for k in mesh_labels}
                    study.add_run(values, fields=data, points=run["points"], cells=run["cells"],
                                  mesh_labels=own)
    except BaseException:
        # A failed import leaves no partial file behind.
        if os.path.exists(out):
            os.remove(out)
        raise
    report = mestra.validate(out)
    return {"ok": not report.errors, "file": out, "rows": len(files),
            "geometry": "fixed" if fixed_geometry else "per run" if one_mesh else "a mesh per run",
            "fields": sorted(field_decl), "mesh_labels": sorted(mesh_labels),
            "left_out": left_out, "notes": notes,
            "findings": [f"{x.rule} {x.path}: {x.message}" for x in report.findings]}


# --- export -------------------------------------------------------------------------------


def export_study(path: str, folder: str) -> dict[str, Any]:
    """One .vtu per row, with parameters.csv and fields.csv, so `import`
    reads the folder back."""
    os.makedirs(folder, exist_ok=True)
    written = []
    with mestra.open(path) as study:
        if study.type == "table":
            raise Problems([f"{path} has no mesh; there is nothing to write as VTK"])
        params = study.names("parameters")
        labels = [n for n in study.names("labels") if n != "file"]
        has_file = "file" in study.names("labels")
        table = study.table(params + labels + (["file"] if has_file else []))
        ids = study.get_row_ids()
        names = []
        stems = [os.path.splitext(os.path.basename(str(table["file"][row])))[0]
                 if has_file and str(table["file"][row]) else f"run_{ids[row]:06d}"
                 for row in range(study.row_count)]
        for row in range(study.row_count):
            # A stem used by more than one row (files appended from several
            # folders) takes the row id, so no file is written twice.
            stem = stems[row] if stems.count(stems[row]) == 1 else f"{stems[row]}_{ids[row]}"
            name = f"{stem}.vtu"
            to_pyvista(study, row).save(os.path.join(folder, name))
            names.append(name)
            written.append(name)
        cols = params + labels
        with open(os.path.join(folder, "parameters.csv"), "w", newline="") as fh:
            out = csv.writer(fh)
            out.writerow(["file"] + cols)
            out.writerow(["units"] + [study.describe(c).get("units", "") if c in params else ""
                                      for c in cols])
            out.writerow(["role"] + [study.describe(c).get("role", "") for c in cols])
            for row in range(study.row_count):
                out.writerow([names[row]] + [_cell(table[c][row]) for c in cols])
        units = {"coordinates": study.describe("coordinates").get("units", "")}
        for where in ("node", "cell"):
            for name in study.names(f"{where}_fields"):
                d = study.describe(name)
                units[d.get("vector") if d.get("vector") and d.get("axis") in AXES else name] = \
                    d.get("units", "")
        with open(os.path.join(folder, "fields.csv"), "w", newline="") as fh:
            out = csv.writer(fh)
            out.writerow(["name", "units"])
            out.writerows(units.items())
    return {"ok": True, "folder": folder, "files": written}


def _cell(v: Any) -> str:
    if isinstance(v, (float, np.floating)):
        return repr(float(v))
    return str(v)


# --- command line -------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="mestra-vtk", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    imp = sub.add_parser("import", help="a folder of VTK runs to one study file")
    imp.add_argument("folder")
    imp.add_argument("-o", "--output", default=None)
    imp.add_argument("--parameters")
    imp.add_argument("--fields")
    imp.add_argument("--skip", default="", help="arrays to leave out, comma separated")
    imp.add_argument("--round-bits", type=int)
    imp.add_argument("--json", action="store_true")
    exp = sub.add_parser("export", help="a study file to one .vtu per run")
    exp.add_argument("study")
    exp.add_argument("folder")
    exp.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.command == "import":
            out = a.output or os.path.normpath(a.folder) + ".mes"
            report = import_folder(a.folder, out, a.parameters, a.fields,
                                   tuple(s for s in a.skip.split(",") if s), a.round_bits)
        else:
            report = export_study(a.study, a.folder)
    except (Problems, mestra.MestraError) as exc:
        problems = exc.problems if isinstance(exc, Problems) else [str(exc)]
        if a.json:
            print(json.dumps({"ok": False, "problems": problems}, indent=1))
        else:
            print(f"{len(problems)} problem{'' if len(problems) == 1 else 's'}:", file=sys.stderr)
            for p in problems:
                print(f"  {p}", file=sys.stderr)
        return 1
    if a.json:
        print(json.dumps(report, indent=1))
    elif "templates" in report:
        print("wrote " + " and ".join(report["templates"]) + "; " + report["next"])
    elif a.command == "import":
        print(f"{report['file']}: {report['rows']} runs, geometry {report['geometry']}, "
              f"{len(report['fields'])} fields, {len(report['mesh_labels'])} mesh labels")
        for line in report["notes"] + [f"left out (not in the CSV): {f}" for f in report["left_out"]]:
            print(f"  {line}")
        for line in report["findings"]:
            print(f"  {line}")
    else:
        print(f"{report['folder']}: {len(report['files'])} files, parameters.csv, fields.csv")
    if "templates" in report:
        return 2
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())

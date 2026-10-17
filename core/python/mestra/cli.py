"""The command line: agents first, people second (interface section 9).

    mestra info FILE [--json]
    mestra validate FILE [--json]
    mestra build DOC.json -o FILE [--json]       mestra build --example
    mestra append FILE DOC.json [--json]
    mestra get FILE NAME... [--where EXPR] [--rows SEL] [--zone LABEL=NAME] -o OUT [--json]

Readable text by default; `--json` prints one document of the shape given
in each command's docstring, which is part of the interface promise.  Big
data goes to files; every problem is reported at once with where it is and
what to do.  Exit status: 0 success, 1 the file or document has errors,
2 a usage error.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from typing import Any

import numpy as np

from . import _lib
from ._lib import MestraError
from ._study import create, open as open_file
from ._validate import validate

EXAMPLE = {
    "writer": "my sweep script",
    "title": "Wing A sweep",
    "license": "CC-BY-4.0",
    "mesh": {"kind": "shared", "per": "fixed", "units": "m", "axes": 3,
             "file": "mesh.npz"},
    "parameters": {"mach": {"units": "1", "role": "condition"},
                   "alpha": {"units": "degree", "role": "condition"}},
    "labels": {"status": {"role": "status", "categories": ["converged", "failed"]}},
    "scalars": {"cl": "1", "cd": "1"},
    "fields": {"p": {"units": "Pa", "at": "node"}},
    "mesh_labels": {"zone": {"at": "cell", "categories": ["inlet", "wall"]}},
    "constants": {"s_ref": [12.5, "m2"]},
    "runs": "runs.csv",
}

EXAMPLE_NOTES = """\
# mesh.npz holds the mesh as NumPy arrays: points (nodes x axes); cells as
#   types (uint8 VTK codes), offsets, connectivity; and each mesh label by
#   name (one value per node or cell).
# runs.csv has a header of column names and one line per run: a value for
#   each parameter and scalar, a name for each label, and for each field the
#   path (relative to the CSV) of a .npy file holding that run's values.
#   When the geometry changes per run (or per group member), a column
#   "points" names a .npy of that run's points, and for a changing mesh a
#   column "cells" names a .npz of its types, offsets and connectivity.
"""


class Problems(Exception):
    """Every problem found in a document, each with its key."""

    def __init__(self, problems: list[tuple[str, str]]) -> None:
        super().__init__("; ".join(f"{k}: {m}" for k, m in problems))
        self.problems = problems


def _emit(args: argparse.Namespace, doc: dict, text: str) -> None:
    if args.json:
        print(json.dumps(doc, indent=1, default=_jsonable))
    else:
        print(text)


def _jsonable(x: Any) -> Any:
    if isinstance(x, np.generic):
        return x.item()
    if isinstance(x, np.ndarray):
        return x.tolist()
    raise TypeError(type(x))


# --- info ---------------------------------------------------------------------------


def _summary(path: str) -> dict:
    """Everything an agent needs to plan, from metadata and the run table."""
    with open_file(path) as f:
        d = f.describe()
        doc: dict[str, Any] = {
            "file": path, "format": d.get("format"), "kind": f.kind, "type": f.type,
            "addons": f.addons, "row_count": f.row_count,
            "file_bytes": os.path.getsize(path),
            "metadata": {k: d[k] for k in ("writer", "created", "file_id", "title", "license",
                                           "references", "source", "generalisation_group",
                                           "trained_on", "evaluated_from") if k in d},
            "parameters": [], "labels": [], "scalars": [], "constants": [],
        }
        for name in f.names("parameters"):
            p = f.describe(name)
            entry = {"name": name, "role": p.get("role"), "units": p.get("units"),
                     "dtype": p.get("dtype")}
            for k in ("lower", "upper", "run_group"):
                if k in p:
                    entry[k] = float(p[k]) if k in ("lower", "upper") else p[k]
            if f.row_count:
                v = f.get_parameter(name)
                entry["range"] = [float(np.nanmin(v)), float(np.nanmax(v))]
            doc["parameters"].append(entry)
        for name in f.names("labels"):
            l = f.describe(name)
            entry = {"name": name, "role": l.get("role")}
            table = _lib.strings_out("mes_table", f._handle(), _lib.b(l.get("category", name)))
            entry["categories"] = table
            if f.row_count:
                names = f.get_label(name).tolist()
                entry["counts"] = {c: names.count(c) for c in table}
            doc["labels"].append(entry)
        for name in f.names("scalars"):
            doc["scalars"].append({"name": name, **f.describe(name)})
        for name in f.names("constants"):
            doc["constants"].append({"name": name, **f.describe(name)})
        if f.type != "table":
            mesh: dict[str, Any] = {"kind": d.get("mesh"), "per": d.get("per")}
            c = f.describe("coordinates")
            mesh.update({"coordinate_units": c.get("units"), "axes": int(c.get("axes", 0)),
                         "precision": c.get("dtype")})
            if f.type == "shared":
                if f._per == "fixed":
                    mesh["nodes"] = int(f.get_points().shape[0])
                types, _, _ = f.get_cells()
                mesh["cells"] = int(types.size)
                mesh["support_id"] = d.get("support_id")
            mesh["node_fields"] = [{"name": n, **f.describe(n)} for n in f.names("node_fields")]
            mesh["cell_fields"] = [{"name": n, **f.describe(n)} for n in f.names("cell_fields")]
            mesh["mesh_labels"] = [{"name": n, **f.describe(n)}
                                   for n in f.names("node_labels") + f.names("cell_labels")]
            doc["mesh"] = mesh
        doc["models"] = [{"id": m, **f.describe(f"models/{m}")} for m in f.names("models")]
    return doc


def _human(doc: dict) -> str:
    kinds = {"table": "table", "shared": "shared mesh", "changing": "changing mesh"}
    head = f"{os.path.basename(doc['file'])}: {kinds.get(doc['type'], doc['type'])}"
    if doc["kind"] == "model":
        head += ", model file"
    else:
        head += f", {doc['row_count']:,} run(s)"
    lines = [head]
    mesh = doc.get("mesh")
    if mesh:
        parts = []
        if "nodes" in mesh:
            parts.append(f"{mesh['nodes']:,} nodes")
        if "cells" in mesh:
            parts.append(f"{mesh['cells']:,} cells")
        parts.append({"fixed": "fixed", "run": "geometry per run"}.get(
            mesh["per"], f"geometry per {mesh['per'][6:]}" if mesh["per"] else ""))
        lines.append("  mesh        " + ", ".join(p for p in parts if p))
    if doc["parameters"]:
        items = []
        for p in doc["parameters"]:
            rng = p.get("range") or ([p["lower"], p["upper"]] if "lower" in p else None)
            r = f" {rng[0]:g}–{rng[1]:g}" if rng else ""
            items.append(f"{p['name']} [{p['units']}]{r}")
        lines.append("  parameters  " + ", ".join(items))
    for l in doc["labels"]:
        counts = l.get("counts")
        what = ", ".join(f"{n} {c}" for c, n in counts.items() if n) if counts else \
            ", ".join(l["categories"])
        lines.append(f"  labels      {l['name']} ({l['role']}): {what}")
    plain = [s for s in doc["scalars"] if not s.get("of")]
    if plain:
        lines.append("  results     " + ", ".join(f"{s['name']} [{s['units']}]" for s in plain))
    if mesh:
        fields = [f"{f['name']} [{f['units']}] at nodes" for f in mesh["node_fields"] if not f.get("of")]
        fields += [f"{f['name']} [{f['units']}] at cells" for f in mesh["cell_fields"] if not f.get("of")]
        if fields:
            lines.append("  fields      " + "; ".join(fields))
        if mesh["mesh_labels"]:
            lines.append("  zones       " + ", ".join(m["name"] for m in mesh["mesh_labels"]))
    rel = [s for s in doc["scalars"] + (mesh["node_fields"] + mesh["cell_fields"] if mesh else [])
           if s.get("of")]
    if rel:
        words = []
        for s in rel:
            if s.get("statistic") == "std":
                words.append(f"{s['name']} (spread of {s['of']})")
            elif s.get("statistic") == "quantile":
                words.append(f"{s['name']} ({float(s['q']) * 100:g}% quantile of {s['of']})")
            else:
                words.append(f"{s['name']} (d{s['of']}/d{s.get('with_respect_to')})")
        lines.append("  also        " + ", ".join(words))
    if doc["constants"]:
        lines.append("  constants   " + ", ".join(f"{c['name']} = {c.get('value')} {c['units']}"
                                                  for c in doc["constants"]))
    for m in doc["models"]:
        lines.append(f"  model       {m['id']}: {m.get('type')} reading {m.get('inputs')}")
    size = doc["file_bytes"]
    unit = "KB" if size < 1e6 else ("MB" if size < 1e9 else "GB")
    scale = 1e3 if unit == "KB" else (1e6 if unit == "MB" else 1e9)
    lines.append(f"  file        {size / scale:.1f} {unit}")
    return "\n".join(lines)


def cmd_info(args: argparse.Namespace) -> int:
    """--json: {"file", "format", "kind", "type", "addons", "row_count", "file_bytes",
    "metadata": {...}, "parameters": [{name, role, units, dtype, lower?, upper?,
    run_group?, range?}], "labels": [{name, role, categories, counts?}],
    "scalars": [{name, ...describe}], "constants": [...], "mesh"?: {kind, per,
    coordinate_units, axes, precision, nodes?, cells?, support_id?, node_fields,
    cell_fields, mesh_labels}, "models": [{id, type, inputs, repr?}]}"""
    doc = _summary(args.file)
    _emit(args, doc, _human(doc))
    return 0


# --- validate -------------------------------------------------------------------------


def cmd_validate(args: argparse.Namespace) -> int:
    """--json: {"file", "ok", "errors", "warnings", "findings": [{rule, severity,
    path, message}]}"""
    r = validate(args.file)
    doc = {"file": args.file, "ok": r.ok, "errors": len(r.errors), "warnings": len(r.warnings),
           "findings": [f.__dict__ for f in r.findings]}
    head = f"{'no' if not r.errors else len(r.errors)} error(s), " \
           f"{'no' if not r.warnings else len(r.warnings)} warning(s)"
    lines = [head] + [f"  {f.rule} {f.path or '(file)'}: {f.message}" for f in r.findings]
    _emit(args, doc, "\n".join(lines))
    return 0 if r.ok else 1


# --- build and append ----------------------------------------------------------------------


_KNOWN_KEYS = {"writer", "title", "license", "references", "source", "mesh", "parameters",
               "labels", "scalars", "fields", "mesh_labels", "constants", "runs",
               "generalisation_group"}


def _check_document(doc: dict, base: str, appending: bool) -> list[tuple[str, str]]:
    """Every problem a document has, before anything is written."""
    problems: list[tuple[str, str]] = []
    for key in doc:
        if key not in _KNOWN_KEYS:
            problems.append((key, f"is not a key of a build document; keys are "
                                  f"{', '.join(sorted(_KNOWN_KEYS))}"))
    if not appending and not doc.get("writer"):
        problems.append(("writer", "name the program writing the file"))
    for group in ("parameters", "scalars", "fields"):
        for name, spec in (doc.get(group) or {}).items():
            units = spec if isinstance(spec, str) else (spec or {}).get("units")
            if not units:
                problems.append((f"{group}.{name}.units", "units are required (e.g. Pa, m s-1, 1)"))
            elif not _lib.units_parse(units):
                problems.append((f"{group}.{name}.units",
                                 f"\"{units}\" does not parse; use UDUNITS form such as m s-1"))
    mesh = doc.get("mesh")
    if mesh:
        for k in ("kind", "per", "units"):
            if not appending and k not in mesh:
                problems.append((f"mesh.{k}", "is required"))
        if mesh.get("file") and not os.path.exists(os.path.join(base, mesh["file"])):
            problems.append(("mesh.file", f"{mesh['file']} does not exist next to the document"))
    runs = doc.get("runs")
    if not runs:
        problems.append(("runs", "name the CSV holding one line per run"))
    elif not os.path.exists(os.path.join(base, runs)):
        problems.append(("runs", f"{runs} does not exist next to the document"))
    return problems


def _read_runs(doc: dict, base: str, study_fields: set[str], labels: set[str],
               problems: list[tuple[str, str]]) -> tuple[dict, dict, list, list]:
    path = os.path.join(base, doc["runs"])
    with open(path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    csv_dir = os.path.dirname(path)
    columns: dict[str, list] = {}
    fields: dict[str, list] = {}
    points: list = []
    cells: list = []
    for i, row in enumerate(rows, start=2):
        for key, value in row.items():
            where = f"runs line {i}, column {key}"
            if key in study_fields:
                f = os.path.join(csv_dir, value)
                if not os.path.exists(f):
                    problems.append((where, f"{value} does not exist"))
                    continue
                fields.setdefault(key, []).append(np.load(f))
            elif key == "points":
                if value:
                    points.append(np.load(os.path.join(csv_dir, value)))
                else:
                    points.append(None)
            elif key == "cells":
                z = np.load(os.path.join(csv_dir, value))
                cells.append((z["types"], z["offsets"], z["connectivity"]))
            elif key in labels:
                columns.setdefault(key, []).append(value)
            else:
                try:
                    columns.setdefault(key, []).append(float(value) if value != "" else np.nan)
                except ValueError:
                    problems.append((where, f"\"{value}\" is not a number"))
    return columns, fields, points, cells


def _add_rows(study: Any, doc: dict, base: str, fields: set[str], labels: set[str]) -> int:
    problems: list[tuple[str, str]] = []
    columns, field_values, points, cells = _read_runs(doc, base, fields, labels, problems)
    if problems:
        raise Problems(problems)
    n = len(next(iter(columns.values()))) if columns else 0
    arrays = {k: np.stack(v) if study._mesh_kind != "changing" else np.concatenate([a.ravel() for a in v])
              for k, v in field_values.items()}
    study.add_runs(columns, fields=arrays, points=points or None, cells=cells or None)
    return n


def cmd_build(args: argparse.Namespace) -> int:
    """--json: {"wrote": FILE, "rows": n, "problems": [{key, message}]}"""
    if args.example:
        print(json.dumps(EXAMPLE, indent=1))
        print(EXAMPLE_NOTES, file=sys.stderr)
        return 0
    if not args.document or not args.output:
        print("mestra build DOC.json -o FILE (or mestra build --example)", file=sys.stderr)
        return 2
    with open(args.document) as fh:
        doc = json.load(fh)
    base = os.path.dirname(os.path.abspath(args.document))
    problems = _check_document(doc, base, appending=False)
    if problems:
        return _report_problems(args, problems)
    mesh = doc.get("mesh") or {}
    try:
        study = create(args.output, writer=doc["writer"], parameters=doc.get("parameters"),
                       labels=doc.get("labels"), scalars=doc.get("scalars"),
                       fields=doc.get("fields"), mesh_labels=doc.get("mesh_labels"),
                       constants={k: tuple(v) for k, v in (doc.get("constants") or {}).items()},
                       mesh=mesh.get("kind"), per=mesh.get("per"),
                       coordinates={"units": mesh["units"], "axes": int(mesh.get("axes", 3))}
                       if mesh else None,
                       title=doc.get("title"), license=doc.get("license"),
                       references=doc.get("references"), source=doc.get("source"),
                       generalisation_group=doc.get("generalisation_group"))
        with study:
            if mesh.get("kind") == "shared":
                z = np.load(os.path.join(base, mesh["file"]))
                cells = (z["types"], z["offsets"], z["connectivity"]) if "types" in z else None
                labels = {k: z[k] for k in (doc.get("mesh_labels") or {})}
                if mesh["per"] == "fixed":
                    study.set_mesh(z["points"], cells, labels)
                else:
                    study.set_mesh(cells=cells, labels=labels, n_nodes=int(z["n_nodes"]))
            n = _add_rows(study, doc, base, set(doc.get("fields") or {}), set(doc.get("labels") or {}))
    except Problems as e:
        _cleanup(args.output)
        return _report_problems(args, e.problems)
    except MestraError as e:
        _cleanup(args.output)
        return _report_problems(args, [(e.path or "file", f"{e.rule + ': ' if e.rule else ''}{e.message}")])
    _emit(args, {"wrote": args.output, "rows": n, "problems": []},
          f"wrote {args.output}: {n} run(s)")
    return 0


def cmd_append(args: argparse.Namespace) -> int:
    """--json: {"appended": FILE, "rows": n, "problems": [{key, message}]}"""
    with open(args.document) as fh:
        doc = json.load(fh)
    base = os.path.dirname(os.path.abspath(args.document))
    problems = _check_document(doc, base, appending=True)
    if problems:
        return _report_problems(args, problems)
    try:
        with open_file(args.file) as f:
            fields = set(f.names("node_fields") + f.names("cell_fields"))
            labels = set(f.names("labels"))
        with open_file(args.file, mode="a") as study:
            n = _add_rows(study, doc, base, fields, labels)
    except Problems as e:
        return _report_problems(args, e.problems)
    except MestraError as e:
        return _report_problems(args, [(e.path or "file", f"{e.rule + ': ' if e.rule else ''}{e.message}")])
    _emit(args, {"appended": args.file, "rows": n, "problems": []},
          f"appended {n} run(s) to {args.file}")
    return 0


def _report_problems(args: argparse.Namespace, problems: list[tuple[str, str]]) -> int:
    doc = {"problems": [{"key": k, "message": m} for k, m in problems]}
    text = f"{len(problems)} problem(s):\n" + "\n".join(f"  {k}: {m}" for k, m in problems)
    if args.json:
        print(json.dumps(doc, indent=1))
    else:
        print(text, file=sys.stderr)
    return 1


def _cleanup(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


# --- get -------------------------------------------------------------------------------------


def _rows_arg(text: str | None) -> Any:
    if text is None:
        return None
    try:
        if ":" in text:
            a, b = text.split(":", 1)
            return slice(int(a) if a else None, int(b) if b else None)
        return [int(x) for x in text.split(",")]
    except ValueError:
        raise MestraError("", f"--rows takes positions (3 or 0,2,5) or a range (0:10), not "
                              f"{text!r}") from None


def cmd_get(args: argparse.Namespace) -> int:
    """--json: {"wrote": OUT, "names": [...], "rows": n, "shape": {name: [...]},
    "units": {name: units}}"""
    out = args.output
    ext = os.path.splitext(out)[1].lower()
    with open_file(args.file) as f:
        rows = _rows_arg(args.rows)
        if args.where:
            chosen = f.select(args.where)
            if rows is not None:
                base = np.arange(f.row_count)[rows]
                chosen = np.intersect1d(chosen, base)
            rows = chosen
        sites = None
        if args.zone:
            label, _, value = args.zone.partition("=")
            d = f.describe(label)
            if f.type == "changing":
                # Each row of a changing mesh has its own mesh labels.
                chosen_rows = np.arange(f.row_count)[rows] if rows is not None else \
                    np.arange(f.row_count)
                if len(np.atleast_1d(chosen_rows)) != 1:
                    raise MestraError("", "--zone on a changing mesh reads one row; give it "
                                          "with --rows N")
                codes = f.get_mesh_label(label, row=int(np.atleast_1d(chosen_rows)[0]))
            else:
                codes = f.get_mesh_label(label)
            table = _lib.strings_out("mes_table", f._handle(), _lib.b(d["category"])) \
                if d.get("category") else None
            want = table.index(value) if table else int(value)
            sites = np.flatnonzero(codes == want)
        data: dict[str, np.ndarray] = {}
        units: dict[str, str] = {}
        fields = set(f.names("node_fields") + f.names("cell_fields"))
        labels = set(f.names("labels"))
        params = set(f.names("parameters"))
        zone_at = f.describe(args.zone.partition("=")[0]).get("location") if args.zone else None
        for name in args.names:
            if name in fields:
                at = f.describe(name).get("location")
                if zone_at and at != zone_at:
                    raise MestraError("", f"the zone {args.zone} marks {zone_at}s and {name} is at "
                                          f"{at}s; choose a zone at {at}s")
                data[name] = f.get_field(name, rows=rows, nodes=sites)
            elif name in labels:
                data[name] = f.get_label(name, rows=rows)
            elif name in params:
                data[name] = f.get_parameter(name, rows=rows)
            elif name == "row":
                data[name] = f.get_row_ids(rows)
            else:
                data[name] = f.get_scalar(name, rows=rows)
            units[name] = f.describe(name).get("units", "") if name != "row" else ""
        ids = f.get_row_ids(rows)
    if ext == ".csv":
        with open(out, "w", newline="") as fh:
            w = csv.writer(fh)
            if any(v.ndim > 1 for v in data.values()):
                if len(data) != 1:
                    raise SystemExit("a field goes to CSV alone (one line per row)")
                (name, arr), = data.items()
                w.writerow(["row"] + [f"{name}[{j}]" for j in range(arr.shape[1])])
                for i, r in enumerate(arr):
                    w.writerow([int(ids[i])] + [repr(float(x)) for x in r])
            else:
                w.writerow(["row"] + list(data))
                for i in range(len(ids)):
                    w.writerow([int(ids[i])] + [str(v[i]) for v in data.values()])
    elif ext == ".npy":
        if len(data) != 1:
            print("a .npy holds one array; use .npz for several", file=sys.stderr)
            return 2
        np.save(out, next(iter(data.values())))
    elif ext == ".npz":
        np.savez(out, row=ids, **data)
    else:
        print(f"OUT ends in .csv, .npy or .npz (got {ext or 'nothing'})", file=sys.stderr)
        return 2
    doc = {"wrote": out, "names": list(data), "rows": int(len(ids)),
           "shape": {k: list(v.shape) for k, v in data.items()}, "units": units}
    _emit(args, doc, f"wrote {out}: " + ", ".join(
        f"{k} {'x'.join(map(str, v.shape))} [{units[k]}]" for k, v in data.items()))
    return 0


# --- entry ------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mestra", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("info", help="describe a file")
    p.add_argument("file")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_info)
    p = sub.add_parser("validate", help="report every rule a file breaks")
    p.add_argument("file")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_validate)
    p = sub.add_parser("build", help="build a file from a JSON document")
    p.add_argument("document", nargs="?")
    p.add_argument("-o", "--output")
    p.add_argument("--example", action="store_true", help="print a filled-in document")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_build)
    p = sub.add_parser("append", help="add runs from a document to a file in place")
    p.add_argument("file")
    p.add_argument("document")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_append)
    p = sub.add_parser("get", help="write selected data to a file")
    p.add_argument("file")
    p.add_argument("names", nargs="+")
    p.add_argument("--where")
    p.add_argument("--rows", help="a:b or i,j,k")
    p.add_argument("--zone", help="LABEL=NAME: the nodes or cells of one zone")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_get)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except MestraError as e:
        if getattr(args, "json", False):
            print(json.dumps({"error": {"rule": e.rule, "path": e.path, "message": e.message}},
                             indent=1))
        else:
            print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

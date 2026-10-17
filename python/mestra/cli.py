"""The command line: `mestra validate`, `mestra info`, `mestra upgrade`.

    $ mestra validate study.mes
    0 error(s), 0 warning(s)

    $ mestra info study.mes
    kind mesh, add-ons: time, model
    ...

    $ mestra upgrade old.mes new.mes

Each finding prints as `<rule> <path>: <message>` and a run ends with
`<n> error(s), <m> warning(s)`. With `--json` each call prints one
document instead: `kind` and `addons` first, then `file`, `format`,
`findings` (each with `rule`, `severity`, `path`, `message`), `errors`
and `warnings` (counts); `info` adds the parameters, labels, scalars,
mesh and callables, and `upgrade` the `source` it read. A command
exits non-zero when it finds an error, so it fits in a build.
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import sys
from collections.abc import Sequence
from typing import Any

import h5py

from . import FORMAT, __version__
from .encoding import read_attr
from .errors import Finding, MestraError
from .model import Dataset, Slot
from .reader import read
from .upgrade import upgrade
from .validator import Report, validate

__all__ = ["main"]


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line; returns the exit status."""
    parser = argparse.ArgumentParser(
        prog="mestra", description="Check, describe and upgrade mestra "
                                   "files.")
    parser.add_argument("--version", action="version",
                        version="mestra %s (format %s)"
                        % (__version__, FORMAT))
    commands = parser.add_subparsers(dest="command")
    check = commands.add_parser(
        "validate", help="report every rule a file breaks",
        description="Print every finding, then the totals. Exits 1 when "
                    "the file has an error; a warning does not.")
    check.add_argument("file")
    check.add_argument("--json", action="store_true",
                       help="print one JSON document")
    show = commands.add_parser(
        "info", help="describe a file",
        description="Print the kind and add-ons first, then the "
                    "parameters, labels, scalars, mesh and callables. "
                    "Reading it costs an open, not a read of the values.")
    show.add_argument("file")
    show.add_argument("--json", action="store_true",
                      help="print one JSON document")
    convert = commands.add_parser(
        "upgrade", help="write the version 1 form of a version 0 file",
        description="Write DST, validated, from the version 0 file SRC, "
                    "which is never changed. Prints what version 1 does "
                    "not keep, and any refusal.")
    convert.add_argument("src")
    convert.add_argument("dst")
    convert.add_argument("--json", action="store_true",
                         help="print one JSON document")
    args = parser.parse_args(list(argv) if argv is not None
                             else sys.argv[1:])
    if args.command is None:
        parser.print_help()
        return 2
    try:
        if args.command == "validate":
            status = _validate(args.file, args.json)
        elif args.command == "info":
            status = _info(args.file, args.json)
        else:
            status = _upgrade(args.src, args.dst, args.json)
        sys.stdout.flush()
    except OSError as exc:
        if not _reader_gone(exc):
            raise
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        return 1
    return status


def _reader_gone(exc: OSError) -> bool:
    """A write to stdout failed because its reader went away."""
    return isinstance(exc, BrokenPipeError) or (
        sys.platform == "win32" and exc.errno == errno.EINVAL)


# -------------------------------------------------------- the commands

def _validate(path: str, as_json: bool) -> int:
    report = validate(path)
    document = _document(path, report)
    _emit(document, report, as_json)
    return 1 if report.errors else 0


def _info(path: str, as_json: bool) -> int:
    try:
        with read(path, strict=False) as ds:
            report = Report(errors=list(ds._problems))
            document = _document(path, report, ds)
            document.update(_describe(ds))
            lines = _lines(ds)
    except (OSError, MestraError) as exc:
        report = Report(errors=[Finding(getattr(exc, "rule", "") or "E01",
                                        "", getattr(exc, "message",
                                                    str(exc)))])
        document = _document(path, report)
        lines = []
    if as_json:
        _print_json(document)
    else:
        print("kind %s, add-ons: %s" % (document["kind"] or "unknown",
                                       ", ".join(document["addons"])
                                       or "none"))
        print("%s  %s" % (path, document["format"] or "not readable"))
        for line in lines:
            print(line)
        for finding in report.findings:
            print(finding)
    return 1 if report.errors else 0


def _upgrade(src: str, dst: str, as_json: bool) -> int:
    try:
        report = upgrade(src, dst)
    except MestraError as exc:
        report = Report(errors=[Finding(exc.rule, exc.path, exc.message,
                                        "error")])
    written = not report.errors and os.path.exists(dst)
    document = _document(dst if written else src, report,
                         kind_from=dst if written else None)
    document["source"] = src
    document["file"] = dst
    _emit(document, report, as_json)
    return 1 if report.errors else 0


# ----------------------------------------------------------- documents

def _document(path: str, report: Report, ds: Dataset | None = None,
              kind_from: str | None = None) -> dict[str, Any]:
    kind, addons, found = None, [], _format(path)
    if ds is None:
        try:
            with read(kind_from or path, strict=False) as opened:
                kind, addons = opened.kind, opened.addons
        except (OSError, MestraError):
            pass
    else:
        kind, addons = ds.kind, ds.addons
    return {
        "kind": kind,
        "addons": addons,
        "file": path,
        "format": found,
        "findings": [{"rule": f.rule, "severity": f.severity,
                      "path": f.path, "message": f.message}
                     for f in report.findings],
        "errors": len(report.errors),
        "warnings": len(report.warnings),
    }


def _format(path: str) -> str | None:
    try:
        with h5py.File(path, "r") as f:
            value = read_attr(f, "format")
    except Exception:
        return None
    return value if isinstance(value, str) else None


def _emit(document: dict[str, Any], report: Report, as_json: bool) -> None:
    if as_json:
        _print_json(document)
        return
    for finding in report.findings:
        print(finding)
    print("%d error(s), %d warning(s)" % (len(report.errors),
                                         len(report.warnings)))


def _print_json(document: dict[str, Any]) -> None:
    print(json.dumps(document, ensure_ascii=False, default=_plain))


def _plain(value: Any) -> Any:
    if hasattr(value, "tolist"):
        return value.tolist()
    return str(value)


def _slot(slot: Slot) -> dict[str, Any]:
    out = {"name": slot.name, "location": slot.location,
           "role": slot.role, "units": slot.units, "varies": slot.varies,
           "components": slot.components,
           "dtype": None if slot.dtype is None else str(slot.dtype),
           "dims": list(slot.dims), "served": slot.served}
    for key in ("callable_id", "output", "statistic", "of", "level",
                "method", "with_respect_to", "significant_bits",
                "category"):
        value = getattr(slot, key)
        if value is not None:
            out[key] = value
    return out


def _describe(ds: Dataset) -> dict[str, Any]:
    out: dict[str, Any] = {
        "rows": ds.row_count,
        "generalisation_group": ds.generalisation_group,
        "parameters": [
            {"name": n, "role": p.role, "units": p.units, "lower": p.lower,
             "upper": p.upper, "run_group": p.run_group,
             "dtype": None if p.dtype is None else str(p.dtype)}
            for n, p in ds.parameters.items()],
        "labels": [
            {"name": n, "role": lab.role, "category": lab.category,
             "entries": None if lab.table is None
             else list(lab.table.entries)}
            for n, lab in ds.labels.items()],
        "scalars": [_slot(s) for s in ds.scalars.values()],
        "mesh": None,
        "callables": [
            {"id": n, "type": _type_of(ds, n),
             "inputs": None if ds._callable_inputs.get(n) is None
             else sorted(ds._callable_inputs[n] or ())}
            for n in ds.callables],
    }
    for key in ("title", "license", "references", "source"):
        out[key] = getattr(ds, key)
    if ds.mesh is not None:
        mesh = ds.mesh
        out["mesh"] = {
            "kind": mesh.kind, "n_nodes": mesh.n_nodes,
            "n_cells": mesh.n_cells, "support_id": mesh.support_id,
            "coordinates": None if mesh.coordinates is None
            else _slot(mesh.coordinates),
            "node_arrays": [_slot(s) for s in mesh.node_arrays.values()],
            "cell_arrays": [_slot(s) for s in mesh.cell_arrays.values()],
        }
    return out


def _type_of(ds: Dataset, identifier: str) -> str:
    try:
        return str(getattr(ds.callables[identifier], "type", ""))
    except MestraError:
        return ""


def _lines(ds: Dataset) -> list[str]:
    lines = ["  %d row(s), written by %r on %s" % (ds.row_count, ds.writer,
                                                  ds.created)]
    if ds.generalisation_group:
        lines[0] += ", unit of generalisation %s" % ds.generalisation_group
    if ds.parameters:
        lines.append("  parameters")
        for name, p in ds.parameters.items():
            bounds = "" if p.lower is None and p.upper is None else \
                "  bounds [%s, %s]" % (p.lower, p.upper)
            run = "  run_group %s" % p.run_group if p.run_group else ""
            lines.append("    %-16s %-10s units %s%s%s"
                         % (name, p.role, p.units, bounds, run))
    if ds.labels:
        lines.append("  labels")
        for name, lab in ds.labels.items():
            table = lab.table
            entries = "" if table is None else "  %s (%s%s)" % (
                lab.category, ", ".join(table.entries[:4]),
                ", ..." if len(table) > 4 else "")
            lines.append("    %-16s %-10s%s" % (name, lab.role, entries))
    if ds.scalars:
        lines.append("  scalars")
        for name, slot in ds.scalars.items():
            lines.append("    %-16s %s" % (name, _slot_line(slot)))
    if ds.mesh is not None:
        mesh = ds.mesh
        lines.append("  mesh  %s, %d node(s), %d cell(s), id %s"
                     % (mesh.kind, mesh.n_nodes, mesh.n_cells,
                        mesh.support_id))
        for where, slot in mesh._arrays().items():
            lines.append("    %-28s %s" % (where, _slot_line(slot)))
    if ds.callables:
        lines.append("  callables")
        for name in ds.callables:
            declared = ds._callable_inputs.get(name)
            lines.append("    %-16s %s%s" % (
                name, _type_of(ds, name),
                "" if declared is None else "  inputs %s"
                % " ".join(sorted(declared))))
    if ds.notes:
        lines.append("  notes")
        for name in sorted(ds.notes):
            lines.append("    %-16s %s" % (name, ds.notes[name]))
    return lines


def _slot_line(slot: Slot) -> str:
    shape = "" if slot._data is None else \
        "x".join(str(n) for n in slot._data.shape)
    parts = ["(%s) %s" % (", ".join(slot.dims), shape), slot.role]
    if slot.units:
        parts.append("units %s" % slot.units)
    if slot.served:
        parts.append("served by %s, output %s" % (slot.callable_id,
                                                 slot.output))
    for key in ("statistic", "of", "with_respect_to", "level", "method",
                "category"):
        value = getattr(slot, key)
        if value is not None:
            parts.append("%s %s" % (key, value))
    return "  ".join(parts)


if __name__ == "__main__":                           # pragma: no cover
    sys.exit(main())

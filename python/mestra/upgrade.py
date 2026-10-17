"""Converting a version 0 file to version 1.

`upgrade(src, dst)` reads a version 0 file with the private version 0
reader, builds the same study in the version 1 layout and writes it to
`dst`, validated; `src` is never changed. Keys move to the root as
parameters and row labels, scalars to the root as row-varying scalars,
the one support to `/mesh` (an `axis` becoming `points`), a time key's
`trajectory_group` becomes `run_group`, and every dataset takes the
version 1 storage defaults. Callable dictionaries are copied through
the codec without being handed to their type, so a dictionary nobody
here can interpret arrives unchanged.

What version 1 does not have is dropped with a report line (`parent`,
`aligned`, the statistics `value` and `mean`, `recomputed`, `weight`
arrays) or refused, naming the feature, before anything is written
(several supports, draws, quantiles, derived arrays, a name that
clashes in the version 1 root). The upgrade never renames and never
creates constants.
"""

from __future__ import annotations

import os
from typing import Any

import h5py
import numpy as np

from . import h5safe
from .callables import OpaqueCallable
from .codec import RESERVED_V0, decode_dict
from .encoding import is_fixed_string, read_attr
from .errors import Finding, MestraError
from .model import (
    CategoryTable,
    Dataset,
    FileSource,
    Label,
    Mesh,
    Parameter,
    Slot,
    _Handle,
    is_reserved_root_name,
)
from .validator import Report, validate
from .writer import write

__all__ = ["upgrade"]

#: Attributes version 1 gives a meaning to, on each kind of object; an
#: unknown version 0 attribute of one of these names is dropped rather
#: than allowed to change meaning in the new file.
_V1_PARAMETER = frozenset(["role", "units", "lower", "upper",
                           "run_group"])
_V1_LABEL = frozenset(["role", "category"])
_V1_SLOT = frozenset(["role", "units", "varies", "components", "source",
                      "coordinates", "category", "output", "of",
                      "statistic", "level", "method", "with_respect_to",
                      "_QuantizeBitRoundNumberOfSignificantBits"])
_V1_MESH = frozenset(["kind", "n_nodes", "n_cells", "support_id"])
_V1_ROOT = frozenset(["format", "writer", "created",
                      "generalisation_group", "title", "license",
                      "references", "source"])


def upgrade(src: str, dst: str) -> Report:
    """Write the version 1 form of the version 0 file `src` to `dst`.

    Returns a `Report`. A refusal is an error finding naming the
    feature or the clash, and nothing is written. On success the
    report carries a line (rule "", a warning) for each thing version
    1 does not keep, followed by the findings of validating `dst`.
    `src` is never changed: a `dst` that names the same file is refused
    with a `MestraError` before anything is read or written.
    """
    from . import _v0

    _refuse_the_same_file(str(src), str(dst))

    report = Report()
    try:
        old = _v0.read(str(src), lazy=True, strict=True)
    except MestraError as exc:
        message = exc.message
        if _format_of(str(src)) == "mestra/1":
            message = "this file is already version 1; there is nothing " \
                      "to upgrade"
        report.errors.append(Finding(exc.rule or "E01", "", message))
        return report
    try:
        found = _v0.validate(old)
        for finding in found.errors:
            report.errors.append(Finding(
                finding.rule, finding.path, "the version 0 file breaks "
                "this rule, so it is not upgraded: %s" % finding.message))
        if report.errors:
            return report
        _refuse(old, report)
        if report.errors:
            return report
        new = _convert(old, report)
        try:
            write(new, str(dst))
        except MestraError as exc:
            report.errors.append(Finding(exc.rule, exc.path, exc.message))
            return report
    finally:
        old.close()
    checked = validate(str(dst))
    report.errors.extend(checked.errors)
    report.warnings.extend(checked.warnings)
    return report


def _refuse_the_same_file(src: str, dst: str) -> None:
    """The upgrade writes a new file; it never replaces its source, by
    the same name, another name for it, or a link to it."""
    same = os.path.realpath(src) == os.path.realpath(dst)
    if not same and os.path.exists(src) and os.path.exists(dst):
        try:
            same = os.path.samefile(src, dst)
        except OSError:
            same = False
    if same:
        raise MestraError(
            "", "dst names the same file as src; upgrade writes a new file "
            "and never changes the original, so give dst another name",
            dst)


def _format_of(path: str) -> Any:
    try:
        with h5py.File(path, "r") as f:
            return read_attr(f, "format")
    except Exception:
        return None


def _line(report: Report, path: str, message: str) -> None:
    report.warnings.append(Finding("", path, message, "warning"))


def _refuse(old: Any, report: Report) -> None:
    """What version 1 cannot hold, each named, before anything is
    written."""
    def refuse(rule: str, path: str, message: str) -> None:
        report.errors.append(Finding(rule, path, message))

    if len(old.supports) > 1:
        refuse("", "", "the file declares %d supports, and a version 1 "
                       "file has at most one mesh; runs on different "
                       "meshes belong in different files"
               % len(old.supports))
    keys = set(old.keys)
    for name in sorted(keys & set(old.scalars)):
        refuse("E33", name, "the key %r and the scalar %r share a name, "
                            "and version 1 holds both in one root; rename "
                            "one in the version 0 file first" % (name, name))
    for kind, names in (("key", sorted(keys)),
                        ("scalar", sorted(old.scalars))):
        for name in names:
            if is_reserved_root_name(name):
                refuse("E33", name, "the %s %r takes a name version 1 "
                                    "reserves in the root; rename it in the "
                                    "version 0 file first" % (kind, name))
    slots: list[tuple[str, Any]] = [
        ("scalars/" + n, s) for n, s in sorted(old.scalars.items())]
    for support in old.supports.values():
        for where, slot in support.arrays().items():
            slots.append(("mesh/" + where, slot))
    for where, slot in slots:
        if slot.statistic == "draw":
            refuse("", where, "this slot holds draws, which version 1 does "
                              "not have; a band is the one uncertainty it "
                              "carries")
        elif slot.statistic == "quantile":
            refuse("", where, "this slot holds a quantile, which version 1 "
                              "does not have")
        if getattr(slot, "role", "scalar") == "derived":
            refuse("", where, "this is a derived array, which version 1 does "
                              "not have")
        if slot.is_callable and getattr(slot, "varies", "row") != "row":
            refuse("", where, "this slot is served by a callable and varies "
                              "by %s; version 1 serves row-varying slots "
                              "only" % slot.varies)
    f = old._file
    holder = f.get("callables") if f is not None else None
    if isinstance(holder, h5py.Group):
        for name in sorted(holder):
            group = holder.get(name)
            if isinstance(group, h5py.Group) and "inputs" in group:
                refuse("E32", "callables/" + name,
                       "this dictionary uses the top-level key inputs, which "
                       "version 1 reserves for the callable's declared "
                       "inputs")
            if isinstance(group, h5py.Group) and \
                    "inputs" in h5safe.attr_names(group):
                refuse("E32", "callables/" + name,
                       "this dictionary uses the top-level key inputs, which "
                       "version 1 reserves for the callable's declared "
                       "inputs")


def _convert(old: Any, report: Report) -> Dataset:
    f = old._file
    holder = _Handle(f)
    new = Dataset(writer=old.writer, created=old.created)
    new._row_count = int(old.n_rows)
    new._handle = holder
    _line(report, "", "dropped the root attribute aligned: version 1 has "
                      "one mesh, so every row is on it")
    for name, attribute in sorted(old.extra.items()):
        if name in _V1_ROOT:
            _line(report, "", "dropped the root attribute %s, which version "
                              "1 defines and the version 0 file did not "
                              "mean in that sense" % name)
        else:
            new._extra[name] = attribute
    for name, table in old.categories.items():
        new.categories[name] = CategoryTable(table.entries)

    for name in old.key_names():
        key = old.keys[name]
        source = _source(holder, f, "/keys/" + name)
        if key.role in ("design", "condition", "time"):
            run_group = key.trajectory_group if key.role == "time" else None
            new.parameters[name] = Parameter(
                name, key.role, units=key.units, lower=key.lower,
                upper=key.upper, run_group=run_group, data=source,
                extra=_kept(key.extra, _V1_PARAMETER, report,
                            "parameters/" + name))
        else:
            new.labels[name] = Label(
                name, key.role,
                category=key.category if key.role != "id" else None,
                data=source, dataset=new,
                extra=_kept(key.extra, _V1_LABEL, report,
                            "labels/" + name))
        if key.parent is not None:
            _line(report, "labels/" + name,
                  "dropped parent = %s: version 1 has no nested groups"
                  % key.parent)
    if old.generalisation_group is not None:
        new.generalisation_group = old.generalisation_group

    for name, scalar in sorted(old.scalars.items()):
        new.scalars[name] = _slot(holder, f, scalar, "/scalars/" + name,
                                  "row", "scalar", "scalars/" + name,
                                  report, new)

    for support in old.supports.values():
        base = "/supports/" + support.name
        if support.kind == "none":
            _line(report, "", "dropped the support %s of kind none: a file "
                              "without a mesh is a table" % support.name)
            continue
        mesh = Mesh("points" if support.kind == "axis" else "mesh",
                    n_nodes=support.n_nodes, n_cells=support.n_cells,
                    stored_support_id=support.stored_support_id,
                    extra=_kept(support.extra, _V1_MESH, report, "mesh"))
        mesh._dataset = new
        for which in ("cell_types", "cell_offsets", "cell_connectivity"):
            if support._cells.get(which) is not None:
                mesh._cells[which] = _source(holder, f,
                                             "%s/%s" % (base, which))
        if support.coordinates is not None:
            mesh.coordinates = _slot(holder, f, support.coordinates,
                                     base + "/coordinates", "node",
                                     "coordinates", "mesh/coordinates",
                                     report, new)
        for which, location, arrays, into in (
                ("node_arrays", "node", support.node_arrays,
                 mesh.node_arrays),
                ("cell_arrays", "cell", support.cell_arrays,
                 mesh.cell_arrays)):
            if which in support.present:
                mesh._present.add(which)
            for name, array in sorted(arrays.items()):
                where = "mesh/%s/%s" % (which, name)
                if array.role == "weight":
                    _line(report, where, "dropped this weight array: "
                                         "integration weights are computed "
                                         "from the coordinates and the "
                                         "connectivity")
                    continue
                role = array.role
                slot = _slot(holder, f, array, "%s/%s/%s" % (base, which,
                                                             name),
                             location, role, where, report, new)
                if role == "normal":
                    slot.role = "field"
                    slot.units = "1"
                    _line(report, where, "a normal is now a field with units "
                                         "1")
                dict.__setitem__(into, name, slot)
        for name, captured in support.opaque.items():
            mesh._opaque[name] = captured
        new.mesh = mesh

    if f is not None and isinstance(f.get("callables"), h5py.Group):
        new._present.add("callables")
        for name in sorted(f["callables"]):
            group = f["callables"][name]
            if not isinstance(group, h5py.Group):
                continue
            kind = read_attr(group, "type") if "type" in \
                h5safe.attr_names(group) else ""
            line = read_attr(group, "repr") if "repr" in \
                h5safe.attr_names(group) else None
            body = decode_dict(group, reserved=RESERVED_V0)
            new.callables[name] = OpaqueCallable(
                kind if isinstance(kind, str) else "", body,
                line if isinstance(line, str) else None)
            new._callable_inputs[name] = None

    if f is not None and isinstance(f.get("notes"), h5py.Group):
        new._present.add("notes")
        group = f["notes"]
        for name in h5safe.attr_names(group):
            raw = group.attrs[name]
            if isinstance(raw, np.ndarray) and raw.ndim == 1 and \
                    raw.dtype.kind in "iuf":
                value: Any = np.array(raw)
            else:
                value = read_attr(group, name)
            if isinstance(value, bool):
                _line(report, "notes", "the note %s was a boolean and is now "
                                       "the integer %d" % (name, int(value)))
                value = int(value)
            if value is None:
                _line(report, "notes", "dropped the note %s, which could not "
                                       "be read as text or a number" % name)
                continue
            new.notes[name] = value
    for name, captured in old.opaque.items():
        new._opaque[name] = captured
    return new


def _source(holder: _Handle, f: h5py.File, path: str) -> FileSource:
    dset = f[path]
    return FileSource(holder, path, dset.shape, dset.dtype,
                      is_fixed_string(dset.dtype))


def _slot(holder: _Handle, f: h5py.File, old: Any, path: str,
          location: str, role: str, where: str, report: Report,
          dataset: Dataset) -> Slot:
    statistic = old.statistic
    if statistic in ("value", "mean"):
        _line(report, where, "dropped statistic = %s: a plain result is the "
                             "value" % statistic)
        statistic = None
    if getattr(old, "recomputed", None) is not None:
        _line(report, where, "dropped recomputed, which version 1 does not "
                             "have")
    slot = Slot(old.name, location=location, role=role, units=old.units,
                varies=getattr(old, "varies", "row"),
                components=getattr(old, "components", None)
                if location != "row" else None,
                source=old.source, output=old.output, statistic=statistic,
                of=old.of if statistic is not None else None,
                level=old.level, method=old.method,
                category=getattr(old, "category", None),
                extra=_kept(old.extra, _V1_SLOT, report, where))
    slot._dataset = dataset
    if old.data is not None:
        slot._data = _source(holder, f, path)
        slot._dims = old.dims
    return slot


def _kept(extra: dict[str, Any], known: frozenset[str], report: Report,
          where: str) -> dict[str, Any]:
    out = {}
    for name, value in sorted(extra.items()):
        if name in known:
            _line(report, where, "dropped the attribute %s, which version 1 "
                                 "defines and the version 0 file did not "
                                 "mean in that sense" % name)
        else:
            out[name] = value
    return out

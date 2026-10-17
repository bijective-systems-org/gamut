"""The validator of the version 1 specification, section 13.

`validate(path)` opens a file and reports every rule it breaks, by
identifier, at concept paths (`parameters/mach`,
`mesh/node_arrays/pressure`, `callables/m1`; the file itself is the
empty path). `validate(dataset)` writes the dataset to a scratch file
and validates that, so a dataset and its file are judged by one set of
rules.

Identifiers are stable: a kept rule keeps its version 0 identifier, and
a retired identifier (E06, E07, E09, E13, E28, E37, E44, E46, W05, W06,
W09, W10, W15, W17) is never emitted.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import h5py
import numpy as np

from . import h5safe, limits
from .encoding import (
    CHUNK_TARGET,
    NULL_SENTINEL,
    SCALE_ATTR_ORDER,
    entry_bytes,
    is_fixed_string,
    leading_bound,
    read_attr,
    site_block,
    string_length,
    support_digest,
)
from .errors import Finding, MestraError, TooLarge
from .model import (
    FORMAT,
    LABEL_ROLES,
    MESH_KINDS,
    MESH_ROLES,
    PARAMETER_ROLES,
    STATISTICS,
    STATUS_WORDS,
    Dataset,
    is_callable_source,
    is_reserved_root_name,
)
from .names import MACHINERY, RESERVED_PREFIX, is_legal_name
from .units import is_parseable

__all__ = ["Report", "validate", "scan", "CELL_TYPES"]

#: The allowed VTK cell type codes and the nodes each takes (version 0
#: section 20); -1 is a polygon of three or more.
CELL_TYPES: dict[int, int] = {
    1: 1, 3: 2, 5: 3, 7: -1, 9: 4, 10: 4, 12: 8, 13: 6, 14: 5,
    21: 3, 22: 6, 23: 8, 24: 10, 25: 20, 26: 15, 27: 13,
}

_ROOT_GROUPS = ("categories", "mesh", "callables", "notes", "private",
                "VTKHDF")
_ROOT_ATTRS = ("format", "writer", "created", "generalisation_group",
               "title", "license", "references", "source")
_PARAMETER_ATTRS = ("role", "units", "lower", "upper", "run_group")
_LABEL_ATTRS = ("role", "category")
_SIGNIFICANT = "_QuantizeBitRoundNumberOfSignificantBits"
_SCALAR_ATTRS = ("role", "units", "varies", "source", "coordinates",
                 "output", "of", "statistic", "level", "method",
                 "with_respect_to", _SIGNIFICANT)
_ARRAY_ATTRS = ("role", "units", "varies", "components", "source",
                "category", "output", "of", "statistic", "level",
                "method", "with_respect_to", _SIGNIFICANT)
_MESH_ATTRS = ("kind", "n_nodes", "n_cells", "support_id")
_MESH_MEMBERS = ("node", "cell", "cell_plus_one", "index", "cell_types",
                 "cell_offsets", "cell_connectivity", "coordinates",
                 "node_arrays", "cell_arrays")
_CALLABLE_ATTRS = ("type", "repr", "inputs")

#: The encoding version 0 section 18 fixes for each attribute this
#: specification names, on the objects it names it on.
_ATTR_KIND = {
    "format": "string", "writer": "string", "created": "string",
    "generalisation_group": "string", "title": "string",
    "license": "string", "references": "string", "source": "string",
    "role": "string", "units": "string", "category": "string",
    "output": "string", "statistic": "string", "of": "string",
    "varies": "string", "kind": "string", "support_id": "string",
    "run_group": "string", "with_respect_to": "string",
    "coordinates": "string", "method": "string", "type": "string",
    "repr": "string", "inputs": "string",
    "n_nodes": "integer", "n_cells": "integer", "components": "integer",
    _SIGNIFICANT: "integer",
    "lower": "float", "upper": "float", "level": "float",
}

#: The findings that say public information is missing (E18).
_MISSING_PUBLIC = ("E02", "E11", "E15", "E17", "E31", "E39")

#: W08: bounds wider than the observed range by more than this.
_STALE_BOUNDS_FACTOR = 4.0

_FILTER_DEFLATE = 1
_FILTER_SHUFFLE = 2

_SIGNED_LE = (np.dtype("<i4"), np.dtype("<i8"))
_FLOATS = (np.dtype("<f4"), np.dtype("<f8"))


@dataclass
class Report:
    """What the validator found, by rule identifier."""

    errors: list[Finding] = field(default_factory=list)
    warnings: list[Finding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when the file is accepted: no error."""
        return not self.errors

    @property
    def unclassified(self) -> list[Finding]:
        """E40 and E41: what the reader could not do, rather than what
        the file says."""
        return [f for f in self.errors if f.rule in ("E40", "E41")]

    @property
    def error_ids(self) -> list[str]:
        return sorted({f.rule for f in self.errors})

    @property
    def warning_ids(self) -> list[str]:
        return sorted({f.rule for f in self.warnings})

    @property
    def findings(self) -> list[Finding]:
        """Everything found, errors first."""
        return self.errors + self.warnings

    def __str__(self) -> str:
        lines = [str(f) for f in self.findings]
        return "\n".join(lines) if lines else "no error and no warning"


def scan(f: h5py.File, limit: int | None = None,
         tables_only: bool = False) -> Report:
    """Validate an open file, reading no more than `limit` elements
    of any dataset; with `tables_only`, reading the category tables
    and no other values, which is what a metadata open may read."""
    checker = _FileValidator(f)
    if limit is not None:
        checker.limit = limit
    checker.tables_only = tables_only
    return checker.run()


def validate(path_or_ds: Any) -> Report:
    """Validate a file by path, or a dataset.

    A file that cannot be opened at all is a report saying so (E01),
    not an exception. A dataset is written to a scratch file without
    checks and that file is validated, so the dataset is judged by the
    same rules as its file; what the dataset cannot be written as is
    reported with the rule the writer named.
    """
    if isinstance(path_or_ds, Dataset):
        return _validate_dataset(path_or_ds)
    try:
        f = h5safe.open_file(str(path_or_ds))
    except MestraError as exc:
        return Report(errors=[Finding(exc.rule, "", exc.message)])
    try:
        return _FileValidator(f).run()
    finally:
        f.close()


def _validate_dataset(ds: Dataset) -> Report:
    from .writer import write

    report = Report()
    for problem in ds._problems:
        _once(report.errors, problem.rule, problem.path, problem.message)
    with tempfile.TemporaryDirectory(prefix="mestra-validate-") as tmp:
        path = os.path.join(tmp, "dataset.mes")
        try:
            write(ds, path, check=False)
        except MestraError as exc:
            if not exc.rule:
                raise                       # the caller's mistake
            _once(report.errors, exc.rule, exc.path, exc.message)
            return report
        found = validate(path)
    for one in found.errors:
        _once(report.errors, one.rule, one.path, one.message)
    for one in found.warnings:
        _once(report.warnings, one.rule, one.path, one.message)
    return report


# --------------------------------------------------------------- a file

class _FileValidator:
    """Every rule of section 13 that a file can break."""

    def __init__(self, f: h5py.File) -> None:
        self.f = f
        self.report = Report()
        self._scales: dict[int, str] | None = None
        self._listed: dict[int, list[Any]] = {}
        self.tables_only = False
        self.limit = limits.MAX_CHECK_ELEMENTS
        self.visited = 0
        self.n_rows = 0
        self.root: dict[str, Any] = {}
        self.categories: dict[str, list[str]] = {}
        self.parameters: dict[str, h5py.Dataset] = {}
        self.labels: dict[str, h5py.Dataset] = {}
        self.scalars: dict[str, Any] = {}
        #: Root objects with a role this reader does not know (W11),
        #: and so outside every other rule.
        self.ignored: set[str] = set()
        self.mesh: h5py.Group | None = None
        self.mesh_arrays: dict[str, dict[str, Any]] = {"node": {},
                                                       "cell": {}}

    @property
    def scales(self) -> dict[int, str]:
        if self._scales is None:
            self._scales = h5safe.scale_index(self.f)
        return self._scales

    # -- collecting findings

    def error(self, rule: str, where: str, message: str) -> None:
        _once(self.report.errors, rule, where, message)

    def warn(self, rule: str, where: str, message: str) -> None:
        _once(self.report.warnings, rule, where, message)

    def note(self, where: str, message: str, rule: str = "E41") -> None:
        self.error(rule, where, message)

    def guarded(self, where: str, step: Any, *args: Any) -> Any:
        try:
            return step(*args)
        except MestraError as exc:
            self.note(exc.path or where, exc.message,
                      exc.rule if exc.rule in ("E40", "E41") else "E41")
        except RecursionError:
            self.note(where, "this object nests deeper than this reader "
                             "will follow")
        except Exception as exc:
            self.note(where, "this object could not be checked: %s"
                             % h5safe._brief(exc))
        return None

    def run(self) -> Report:
        if not self.guarded("", self._version):
            return self.report
        for where, step in (("", self._collect), ("", self._root),
                            ("categories", self._categories),
                            ("", self._parameters), ("", self._labels),
                            ("", self._run_table),
                            ("", self._scalars), ("mesh", self._mesh),
                            ("", self._relations),
                            ("callables", self._callables),
                            ("", self._bytes), ("private", self._private)):
            self.guarded(where, step)
        return self.report

    # -- reading

    def values(self, dset: h5py.Dataset, where: str) -> Any:
        """A dataset's values, or None: a metadata open reads only the
        category tables, and a dataset above the check limit is left
        unchecked rather than read."""
        if self.tables_only and not where.startswith("categories/"):
            return None
        try:
            return np.asarray(h5safe.read_values(dset, where,
                                                 limit=self.limit))
        except TooLarge:
            return None
        except MestraError as exc:
            self.note(where, exc.message)
        except Exception as exc:
            self.note(where, "this dataset could not be read: %s"
                             % h5safe._brief(exc))
        return None

    def members(self, group: h5py.Group, where: str) -> list[Any]:
        at = h5safe.address(group)
        listed = self._listed.get(at) if at is not None else None
        if listed is None:
            listed = h5safe.members(group)
            if at is not None:
                self._listed[at] = listed
        out = []
        for member in listed:
            if member.usable:
                out.append(member)
            else:
                self.note(_join(where, member.name),
                          member.problem or "this member cannot be read",
                          member.rule)
        return out

    def where(self, name: str) -> str:
        """The concept path of a root object."""
        if name in self.parameters:
            return "parameters/" + name
        if name in self.labels:
            return "labels/" + name
        if name in self.scalars:
            return "scalars/" + name
        return name

    def concept(self, path: str) -> str:
        """The concept path of an HDF5 path."""
        parts = path.strip("/").split("/")
        if parts == [""]:
            return ""
        if len(parts) == 1:
            return self.where(parts[0])
        return "/".join(parts)

    # -- the version decides whether to read at all

    def _version(self) -> bool:
        if "format" not in self.f.attrs:
            self.error("E01", "", "the root attribute format is missing")
            self.error("E17", "", "format is required")
            return False
        text = read_attr(self.f, "format")
        if text != FORMAT:
            from .reader import version_message
            self.error("E01", "", version_message(text))
            return False
        return True

    def _collect(self) -> None:
        self.root = {m.name: m for m in self.members(self.f, "")}
        found = self.root.get("row")
        if found is not None and isinstance(found.obj, h5py.Dataset) and \
                found.obj.shape:
            self.n_rows = int(found.obj.shape[0])
        group = self._group("categories")
        if group is not None:
            for member in self.members(group, "categories"):
                if isinstance(member.obj, h5py.Dataset):
                    self.categories[member.name] = self._strings_in(
                        member.obj, "categories/" + member.name)
        for name, member in self.root.items():
            obj = member.obj
            if name in _ROOT_GROUPS:
                continue
            if isinstance(obj, h5py.Dataset) and h5safe.is_scale(obj):
                continue
            if isinstance(obj, h5py.Group) and "role" not in _names(obj):
                continue                          # an unknown group, W11
            role = _attr(obj, "role")
            if role in PARAMETER_ROLES and isinstance(obj, h5py.Dataset):
                self.parameters[name] = obj
            elif role in LABEL_ROLES and isinstance(obj, h5py.Dataset):
                self.labels[name] = obj
            elif role == "scalar":
                self.scalars[name] = obj
            elif role is None:
                continue                          # E39 in _root
            elif role in PARAMETER_ROLES or role in LABEL_ROLES:
                self.note(name, "a %s is a dataset, and this is a group"
                          % ("parameter" if role in PARAMETER_ROLES
                             else "label"))
                self.ignored.add(name)
            else:
                self.ignored.add(name)
        self.mesh = self._group("mesh")

    def _group(self, name: str) -> h5py.Group | None:
        found = self.root.get(name)
        if found is None or not isinstance(found.obj, h5py.Group):
            return None
        return found.obj

    def _strings_in(self, dset: h5py.Dataset, where: str) -> list[str]:
        values = self.values(dset, where)
        if values is None:
            return []
        return [h5safe.decode_bytes(v) if isinstance(v, bytes) else str(v)
                for v in values.reshape(-1)]

    # -- the root

    def _root(self) -> None:
        attrs = _names(self.f)
        for name in ("format", "writer", "created"):
            if name not in attrs:
                self.error("E17", "", "the root attribute %s is missing"
                           % name)
        if "created" in attrs and not _is_iso_utc(
                read_attr(self.f, "created")):
            self.warn("W14", "", "created is not an ISO 8601 UTC "
                                 "timestamp")
        for name in attrs:
            if name not in _ROOT_ATTRS:
                self.warn("W11", "", "this reader does not know the root "
                                     "attribute %s, and ignores it" % name)
        if "generalisation_group" in attrs:
            unit = read_attr(self.f, "generalisation_group")
            if unit not in self.labels or \
                    _attr(self.labels[unit], "role") != "group":
                self.error("E47", "", "generalisation_group names %r, which "
                                      "is not a group label" % (unit,))
        for name, member in self.root.items():
            obj = member.obj
            if name in _ROOT_GROUPS:
                if name in ("private", "VTKHDF"):
                    continue
                if not isinstance(obj, h5py.Group):
                    self.note(name, "this is a dataset where the format "
                                    "has a group")
                continue
            if isinstance(obj, h5py.Dataset) and h5safe.is_scale(obj):
                continue
            if isinstance(obj, h5py.Group) and "role" not in _names(obj):
                self.warn("W11", name, "this reader does not know the "
                                       "group %s, and ignores it" % name)
                continue
            role = _attr(obj, "role")
            if role is None:
                self.error("E39", name, "a dataset in the root carries "
                                        "role: a parameter role, a label "
                                        "role, or scalar")
            elif name in self.ignored and role not in PARAMETER_ROLES \
                    and role not in LABEL_ROLES:
                self.warn("W11", name, "this reader does not know the "
                                       "role %r, and ignores this object"
                          % (role,))

    def _categories(self) -> None:
        group = self._group("categories")
        if group is None:
            return
        for member in self.members(group, "categories"):
            where = "categories/" + member.name
            self._name(member.name, where)
            if not isinstance(member.obj, h5py.Dataset):
                self.note(where, "a category table is a dataset, and this "
                                 "is a group")
                continue
            if not is_fixed_string(member.obj.dtype):
                self.error("E20", where, "a category table is a "
                                         "fixed-length UTF-8 string "
                                         "dataset")
                continue
            self._strings_of(member.obj, where, "E26")

    def _strings_of(self, dset: h5py.Dataset, where: str,
                    rule: str) -> None:
        """E26 (or E32 in a dictionary), and W13."""
        size = string_length(dset.dtype) or 1
        values = self.values(dset, where)
        if values is None:
            return
        longest = 0
        for raw in values.reshape(-1):
            if not isinstance(raw, bytes):
                continue
            body = raw.rstrip(b"\x00")
            longest = max(longest, len(body))
            if b"\x00" in body:
                self.error(rule, where, "a fixed-length string holds a NUL "
                                        "byte outside its trailing padding")
            try:
                body.decode("utf-8")
            except UnicodeDecodeError:
                self.error(rule, where, "a fixed-length string is not "
                                        "valid UTF-8")
        if size > max(1, longest):
            self.warn("W13", where, "this string dataset is %d bytes wide "
                                    "where %d would do"
                      % (size, max(1, longest)))

    # -- parameters

    def _parameters(self) -> None:
        for name in _utf8(self.parameters):
            dset = self.parameters[name]
            where = "parameters/" + name
            role = _attr(dset, "role")
            self._root_name(name, where)
            known = _PARAMETER_ATTRS if role == "time" else \
                tuple(a for a in _PARAMETER_ATTRS if a != "run_group")
            self._unknown_attrs(dset, where, known)
            self._units(dset, where, required=True)
            if dset.dtype not in (np.dtype("<f8"), np.dtype("<i8")):
                self.error("E20", where, "a parameter is little-endian "
                                         "float64 or int64, and this is %s"
                           % dset.dtype)
            self._rows(dset, where)
            self._bounds(dset, where)
            if role == "time" and "run_group" in _names(dset):
                group = _attr(dset, "run_group")
                if group not in self.labels or \
                        _attr(self.labels[group], "role") != "group":
                    self.error("E47", where, "run_group names %r, which is "
                                             "not a group label" % (group,))

    def _bounds(self, dset: h5py.Dataset, where: str) -> None:
        """W04 and W08: the declared bounds against the values."""
        lower = _attr(dset, "lower")
        upper = _attr(dset, "upper")
        lower = lower if isinstance(lower, (int, float)) and \
            not isinstance(lower, bool) else None
        upper = upper if isinstance(upper, (int, float)) and \
            not isinstance(upper, bool) else None
        if lower is None and upper is None:
            return
        values = self.values(dset, where)
        if values is None or values.dtype.kind not in "fiu" or \
                not values.size:
            return
        finite = values[np.isfinite(values)] if values.dtype.kind == "f" \
            else values
        if not finite.size:
            return
        said = w04(values, lower, upper)
        if said:
            self.warn("W04", where, said)
            return
        if lower is None or upper is None:
            return
        observed = float(np.max(finite)) - float(np.min(finite))
        declared = float(upper) - float(lower)
        if observed > 0 and declared > _STALE_BOUNDS_FACTOR * observed:
            self.warn("W08", where, "the declared bounds are %.1f times "
                                    "wider than the observed range, which "
                                    "is what stale bounds look like"
                      % (declared / observed))

    # -- labels

    def _labels(self) -> None:
        roles: dict[str, list[str]] = {}
        for name in _utf8(self.labels):
            dset = self.labels[name]
            where = "labels/" + name
            role = _attr(dset, "role")
            roles.setdefault(role, []).append(name)
            self._root_name(name, where)
            self._unknown_attrs(dset, where, _LABEL_ATTRS if role != "id"
                                else ("role",))
            self._rows(dset, where)
            if role == "id":
                if not is_fixed_string(dset.dtype) and \
                        dset.dtype != np.dtype("<i8"):
                    self.error("E20", where, "an id label is little-endian "
                                             "int64 or a fixed-length UTF-8 "
                                             "string, and this is %s"
                               % dset.dtype)
                elif is_fixed_string(dset.dtype):
                    self._strings_of(dset, where, "E26")
                self._unique(dset, where)
                continue
            if dset.dtype not in _SIGNED_LE:
                self.error("E20", where, "a %s label stores little-endian "
                                         "int32 or int64 codes, and this "
                                         "is %s" % (role, dset.dtype))
            self._codes(dset, where, required=True)
            if role == "group":
                self._unused(dset, where)
            if role == "status":
                table = self.categories.get(_attr(dset, "category") or "")
                values = self.values(dset, where)
                if table and values is not None and \
                        values.dtype.kind in "iu":
                    said = w02(values, table)
                    if said:
                        self.warn("W02", where, said)
        for role in ("status", "id"):
            found = roles.get(role, [])
            if len(found) > 1:
                self.error("E03", "labels/" + found[1],
                           "a file has at most one %s label, and this one "
                           "has %d: %s" % (role, len(found),
                                           ", ".join(found)))

    def _codes(self, dset: h5py.Dataset, where: str,
               required: bool) -> None:
        """E39 and E10: codes against the table they name."""
        if "category" not in _names(dset):
            if required:
                self.error("E39", where, "a table-backed label names its "
                                         "category table")
            return
        name = _attr(dset, "category")
        table = self.categories.get(name)
        if table is None and name not in self.categories:
            self.error("E39", where, "the category table %r is not under "
                                     "categories" % (name,))
            return
        values = self.values(dset, where)
        if values is None or not values.size or \
                values.dtype.kind not in "iu":
            return
        outside = values[(values < 0) | (values >= len(table or []))]
        if outside.size:
            self.error("E10", where, "the code %d is outside a category "
                                     "table of %d entries"
                       % (int(outside.reshape(-1)[0]), len(table or [])))

    def _unused(self, dset: h5py.Dataset, where: str) -> None:
        """W07: a group's table entry no row uses."""
        table = self.categories.get(_attr(dset, "category") or "")
        values = self.values(dset, where)
        if not table or values is None or values.dtype.kind not in "iu":
            return
        used = {int(v) for v in values.reshape(-1)}
        unused = [t for at, t in enumerate(table) if at not in used]
        if unused:
            self.warn("W07", where, "the category table has %s no row uses: "
                                    "%s" % (_count(len(unused), "an entry",
                                                   "entries"),
                                            ", ".join(unused[:3])))

    def _unique(self, dset: h5py.Dataset, where: str) -> None:
        """E48: an id appearing twice."""
        values = self.values(dset, where)
        if values is None or not values.size:
            return
        flat = values.reshape(-1)
        unique, counts = np.unique(flat, return_counts=True)
        repeated = unique[counts > 1]
        if repeated.size:
            first = repeated[0]
            if isinstance(first, bytes):
                first = h5safe.decode_bytes(first)
            self.error("E48", where, "%s appear more than once; the first "
                                     "is %r" % (_count(int(repeated.size),
                                                       "an id", "ids"),
                                                _plain(first)))

    # -- splits, units of generalisation, runs

    def _run_table(self) -> None:
        """W01 and W18, from the labels and the time parameters."""
        unit = _attr(self.f, "generalisation_group")
        splits = [n for n in _utf8(self.labels)
                  if _attr(self.labels[n], "role") == "split"]
        runs: list[tuple[str, str]] = []
        for name in _utf8(self.parameters):
            dset = self.parameters[name]
            group = _attr(dset, "run_group")
            if _attr(dset, "role") == "time" and group in self.labels and \
                    _attr(self.labels[group], "role") == "group":
                runs.append((name, group))
        holders: list[str] = []
        if unit in self.labels and \
                _attr(self.labels[unit], "role") == "group":
            holders.append(unit)
        for _, group in runs:
            if group not in holders:
                holders.append(group)
        for split in splits:
            parts = self.values(self.labels[split], "labels/" + split)
            if parts is None:
                continue
            for group in holders:
                codes = self.values(self.labels[group], "labels/" + group)
                if codes is None or len(codes) != len(parts):
                    continue
                table = self.categories.get(
                    _attr(self.labels[group], "category") or "")
                kind = "unit of generalisation" if group == unit \
                    else "run"
                said = w01(codes, parts, group, table, kind)
                if said:
                    self.warn("W01", "labels/" + split, said)
        for name, group in runs:
            times = self.values(self.parameters[name], "parameters/" + name)
            codes = self.values(self.labels[group], "labels/" + group)
            if times is None or codes is None or len(times) != len(codes):
                continue
            table = self.categories.get(
                _attr(self.labels[group], "category") or "")
            said = w18(times, codes, table)
            if said:
                self.warn("W18", "parameters/" + name, said)

    # -- scalars

    def _scalars(self) -> None:
        names = list(self.parameters) + list(self.labels)
        for name in _utf8(self.scalars):
            obj = self.scalars[name]
            where = "scalars/" + name
            self._root_name(name, where)
            self._unknown_attrs(obj, where, _SCALAR_ATTRS)
            self._units(obj, where, required=True)
            attrs = _names(obj)
            varies = _attr(obj, "varies")
            if varies is None:
                self.error("E39", where, "a scalar carries varies")
            elif varies not in ("row", "none"):
                self.error("E04", where, "a scalar varies by row or not at "
                                         "all, and this varies by %r"
                           % (varies,))
            served = self._source(obj, where)
            self._statistic(obj, where, served)
            if served and varies not in (None, "row"):
                self.error("E49", where, "a served slot varies by row, and "
                                         "this one varies by %s" % varies)
            if varies == "row" and names and "coordinates" not in attrs:
                self.error("E39", where, "a row-varying scalar carries the "
                                         "CF coordinates attribute naming "
                                         "the parameters and labels")
            if varies == "none" and "coordinates" in attrs:
                self.error("E39", where, "a constant has no row axis, so it "
                                         "carries no CF coordinates "
                                         "attribute")
            if not isinstance(obj, h5py.Dataset):
                continue
            if obj.dtype not in _FLOATS:
                self.error("E20", where, "a scalar is little-endian float32 "
                                         "or float64, and this is %s"
                           % obj.dtype)
            if varies == "row":
                self._rows(obj, where)
            elif varies == "none" and obj.ndim != 0:
                self.error("E04", where, "a constant has no axes, and this "
                                         "has %d" % obj.ndim)
            self._finite(obj, where)
            self._band(obj, where)

    # -- the mesh

    def _mesh(self) -> None:
        group = self.mesh
        if group is None:
            return
        where = "mesh"
        attrs = _names(group)
        self._unknown_attrs(group, where, _MESH_ATTRS)
        for name in _MESH_ATTRS:
            if name not in attrs:
                self.error("E39", where, "the mesh carries %s" % name)
        kind = _attr(group, "kind")
        if kind is not None and kind not in MESH_KINDS:
            self.error("E02", where, "%r is not a kind of mesh; it is mesh "
                                     "or points" % (kind,))
        n_nodes = _attr(group, "n_nodes")
        n_nodes = n_nodes if isinstance(n_nodes, int) else 0
        n_cells = _attr(group, "n_cells")
        n_cells = n_cells if isinstance(n_cells, int) else 0
        inside = {m.name: m.obj for m in self.members(group, where)}
        cells = {w: inside[w] for w in ("cell_types", "cell_offsets",
                                        "cell_connectivity")
                 if isinstance(inside.get(w), h5py.Dataset)}
        if kind == "mesh" and len(cells) != 3:
            self.error("E38", where, "a mesh of kind mesh carries "
                                     "cell_types, cell_offsets and "
                                     "cell_connectivity")
        if kind == "points" and (cells or "cell" in inside or
                                 "cell_arrays" in inside):
            self.error("E38", where, "a points mesh carries no cell "
                                     "datasets, no cell dimension and no "
                                     "cell arrays")
        self.guarded(where, self._cells, cells, n_nodes,
                     n_cells if kind == "mesh" else None)
        coordinates = inside.get("coordinates")
        if kind in MESH_KINDS and coordinates is None:
            self.error("E03", where, "the mesh has exactly one coordinates "
                                     "array")
        if coordinates is not None:
            self.guarded("mesh/coordinates", self._array,
                         "mesh/coordinates", coordinates, "node", kind,
                         n_nodes, n_cells, True)
        for which, location in (("node_arrays", "node"),
                                ("cell_arrays", "cell")):
            holder = inside.get(which)
            if holder is None:
                continue
            if not isinstance(holder, h5py.Group):
                self.note("mesh/" + which, "this is a dataset where the "
                                           "format has a group")
                continue
            for member in self.members(holder, "mesh/" + which):
                path = "mesh/%s/%s" % (which, member.name)
                self.mesh_arrays[location][member.name] = member.obj
                self.guarded(path, self._array, path, member.obj,
                             location, kind, n_nodes, n_cells, False)
        self.guarded(where, self._support_id, group, kind, n_nodes, cells,
                     coordinates)
        for name, obj in inside.items():
            if name in _MESH_MEMBERS:
                continue
            if isinstance(obj, h5py.Group):
                self.warn("W11", "mesh/" + name, "this reader does not know "
                                                 "the group %s, and ignores "
                                                 "it" % name)
            elif not h5safe.is_scale(obj):
                self.warn("W11", "mesh/" + name, "this reader does not know "
                                                 "the dataset %s, and "
                                                 "ignores it" % name)

    def _cells(self, cells: dict[str, h5py.Dataset], n_nodes: int,
               n_cells: int | None) -> None:
        """E05 and E20 to E24 over the connectivity."""
        if len(cells) != 3:
            return
        if cells["cell_types"].dtype != np.dtype("u1"):
            self.error("E20", "mesh/cell_types", "cell_types is uint8")
        for which in ("cell_offsets", "cell_connectivity"):
            if cells[which].dtype != np.dtype("<i8"):
                self.error("E20", "mesh/" + which,
                           "%s is little-endian int64" % which)
        types = self.values(cells["cell_types"], "mesh/cell_types")
        offsets = self.values(cells["cell_offsets"], "mesh/cell_offsets")
        connectivity = self.values(cells["cell_connectivity"],
                                   "mesh/cell_connectivity")
        if types is None or offsets is None or connectivity is None:
            return
        if (types.dtype.kind not in "iu" or offsets.dtype.kind not in "iu"
                or connectivity.dtype.kind not in "iu"):
            return
        if n_cells is not None and len(types) != n_cells:
            self.error("E05", "mesh/cell_types", "the mesh declares %d "
                                                 "cells and cell_types holds "
                                                 "%d" % (n_cells, len(types)))
        for code in np.unique(types):
            if int(code) not in CELL_TYPES:
                self.error("E21", "mesh/cell_types", "%d is not a cell type "
                                                     "code" % int(code))
        bad = (len(offsets) != len(types) + 1
               or (offsets.size and offsets[0] != 0)
               or bool(np.any(np.diff(offsets) < 0))
               or (offsets.size and offsets[-1] != len(connectivity)))
        if bad:
            self.error("E23", "mesh/cell_offsets", "cell_offsets starts at "
                                                   "0, does not decrease, "
                                                   "and ends at the length "
                                                   "of cell_connectivity")
        else:
            widths = np.diff(offsets)
            for at, code in enumerate(types):
                wanted = CELL_TYPES.get(int(code))
                width = int(widths[at])
                if wanted is None:
                    continue
                if (wanted == -1 and width < 3) or \
                        (wanted != -1 and width != wanted):
                    self.error("E22", "mesh/cell_offsets",
                               "cell %d is type %d and the offsets give it "
                               "%d nodes" % (at, int(code), width))
                    break
        if connectivity.size:
            outside = connectivity[(connectivity < 0)
                                   | (connectivity >= n_nodes)]
            if outside.size:
                self.error("E24", "mesh/cell_connectivity",
                           "the value %d is outside [0, %d)"
                           % (int(outside[0]), n_nodes))

    def _support_id(self, group: h5py.Group, kind: Any, n_nodes: int,
                    cells: dict[str, Any], coordinates: Any) -> None:
        """E08: the digest against the stored arrays (section 5.3)."""
        if "support_id" not in _names(group) or kind not in MESH_KINDS:
            return
        axis = None
        if kind == "points":
            if not isinstance(coordinates, h5py.Dataset):
                return
            axis = self.values(coordinates, "mesh/coordinates")
            if axis is None or axis.dtype.kind != "f":
                return
            axis = axis.astype("<f8")
            parts: list[Any] = [None, None, None]
        else:
            parts = []
            for which in ("cell_types", "cell_offsets",
                          "cell_connectivity"):
                if which not in cells:
                    parts.append(None)
                    continue
                values = self.values(cells[which], "mesh/" + which)
                if values is None:
                    return
                parts.append(values)
        digest = support_digest(n_nodes, parts[0], parts[1], parts[2],
                                axis)
        if _attr(group, "support_id") != digest:
            self.error("E08", "mesh", "the stored support_id does not match "
                                      "the arrays; they hash to %s" % digest)

    def _array(self, where: str, member: Any, location: str, kind: Any,
               n_nodes: int, n_cells: int, coordinates: bool) -> None:
        name = where.rsplit("/", 1)[-1]
        if not coordinates:
            self._name(name, where)
        self._unknown_attrs(member, where, _ARRAY_ATTRS)
        attrs = _names(member)
        role = _attr(member, "role")
        if role is None:
            self.error("E02", where, "an array in the mesh carries a role")
        elif role not in MESH_ROLES:
            self.error("E02", where, "%r is not a role of a mesh array"
                       % (role,))
        elif coordinates and role != "coordinates":
            self.error("E02", where, "the mesh's coordinates carry role = "
                                     "coordinates")
        elif not coordinates and role == "coordinates":
            self.error("E03", where, "the mesh has exactly one coordinates "
                                     "array, and this is a second")
        if role in ("field", "coordinates"):
            self._units(member, where, required=True)
        elif role == "label" and "units" in attrs:
            self.warn("W11", where, "a region label carries no units, and "
                                    "this reader ignores them")
        if role == "label":
            self._codes(member, where, required=False)
        varies = _attr(member, "varies")
        if varies is None:
            self.error("E39", where, "an array carries varies")
            varies = "none"
        components = _attr(member, "components")
        if components is None:
            self.error("E31", where, "an array declares its components")
        served = self._source(member, where)
        self._statistic(member, where, served)
        if served and varies != "row":
            self.error("E49", where, "a served slot varies by row, and this "
                                     "one varies by %s" % varies)
        if coordinates and kind == "points":
            if isinstance(components, int) and not 1 <= components <= 3:
                self.error("E03", where, "points coordinates have one to "
                                         "three components, and these have "
                                         "%d" % components)
            if served:
                self.error("E49", where, "points coordinates are stored, "
                                         "never served")
            if varies != "none":
                self.error("E35", where, "points coordinates do not vary")
        if not (varies in ("none", "row") or varies.startswith("group:")):
            self.error("E04", where, "varies is none, row or group:<k>, and "
                                     "this is %r" % (varies,))
            return
        if varies.startswith("group:"):
            group = varies[len("group:"):]
            if group not in self.labels or \
                    _attr(self.labels[group], "role") != "group":
                self.error("E04", where, "varies names %r, which is not a "
                                         "group label" % group)
        if not isinstance(member, h5py.Dataset):
            return
        if role == "label":
            if member.dtype not in _SIGNED_LE:
                self.error("E20", where, "a region label is little-endian "
                                         "int32 or int64, and this is %s"
                           % member.dtype)
        elif role in ("field", "coordinates") and \
                member.dtype not in _FLOATS:
            self.error("E20", where, "a %s is little-endian float32 or "
                                     "float64, and this is %s"
                       % (role, member.dtype))
        dims = _logical(member, self.scales)
        wanted = 3 if varies != "none" else 2
        if member.ndim != wanted:
            self.error("E04", where, "an array with varies = %s has %d axes, "
                                     "and this one has %d"
                       % (varies, wanted, member.ndim))
        elif varies != "none" and dims and dims[0] and dims[0] != varies:
            self.error("E04", where, "varies = %s, and the leading "
                                     "dimension is %s" % (varies, dims[0]))
        width = n_nodes if location == "node" else n_cells
        if member.ndim >= 2 and member.shape[-2] != width:
            self.error("E05", where, "the mesh has %d %ss and the array has "
                                     "%d" % (width, location,
                                             member.shape[-2]))
        if isinstance(components, int) and member.ndim and \
                member.shape[-1] != components:
            self.error("E31", where, "components is %d and the component "
                                     "dimension is %d long"
                       % (components, member.shape[-1]))
        if varies == "row" and member.ndim == wanted:
            self._rows(member, where)
        if varies.startswith("group:") and member.ndim == wanted:
            group = varies[len("group:"):]
            if group in self.labels:
                table = self.categories.get(
                    _attr(self.labels[group], "category") or "")
                if table is not None and member.shape[0] != len(table):
                    self.error("E34", where, "the group %s has %d categories "
                                             "and this array has %d "
                                             "instances"
                               % (group, len(table), member.shape[0]))
        if role in ("field",):
            self._finite(member, where)
            self._band(member, where)

    # -- relations

    def _relations(self) -> None:
        """E12 on `of` and `with_respect_to` (section 7)."""
        scalars = self.scalars
        for name in _utf8(scalars):
            self._relation(scalars[name], "scalars/" + name, scalars,
                           None)
        for location in ("node", "cell"):
            arrays = self.mesh_arrays[location]
            for name in _utf8(arrays):
                self._relation(arrays[name], "mesh/%s_arrays/%s"
                               % (location, name), arrays, location)

    def _relation(self, obj: Any, where: str, group: Mapping[str, Any],
                  location: str | None) -> None:
        attrs = _names(obj)
        statistic = _attr(obj, "statistic") if "statistic" in attrs \
            else None
        wrt = _attr(obj, "with_respect_to") if "with_respect_to" in attrs \
            else None
        if statistic is None and wrt is None:
            return
        of = _attr(obj, "of")
        if of is None:
            return                              # E12 in _statistic
        if wrt == "coordinates":
            if location != "node":
                self.error("E12", where, "a derivative with respect to "
                                         "coordinates is a node array")
                return
            target = self.scalars.get(of)
            if target is None:
                self.error("E12", where, "of names %r, and a derivative "
                                         "with respect to coordinates names "
                                         "a scalar" % (of,))
            elif _is_relation(target):
                self.error("E12", where, "of names %r, which is itself a "
                                         "relation" % (of,))
            return
        if wrt is not None and wrt not in self.parameters:
            self.error("E12", where, "with_respect_to names %r, which is "
                                     "neither a parameter nor coordinates"
                       % (wrt,))
        target = group.get(of)
        if target is None:
            elsewhere = of in self.labels or of in self.parameters
            self.error("E12", where, "of names %r, %s" % (
                of, "which is not a scalar or a field" if elsewhere
                else "which is not in this slot's group"))
            return
        if _attr(target, "role") == "label":
            self.error("E12", where, "of names %r, a region label" % (of,))
            return
        if _is_relation(target):
            self.error("E12", where, "of names %r, which is itself a "
                                     "relation" % (of,))
            return
        mine = (_attr(obj, "varies"), _attr(obj, "components"))
        theirs = (_attr(target, "varies"), _attr(target, "components"))
        if mine != theirs:
            self.error("E12", where, "a relation has the shape and varies "
                                     "of its of; %r varies by %s with %s "
                                     "component(s), and this by %s with %s"
                       % (of, theirs[0], theirs[1], mine[0], mine[1]))
            return
        if statistic in ("band", "std") and \
                _attr(obj, "units") != _attr(target, "units"):
            self.error("E12", where, "a %s carries the units string of %r "
                                     "(%r), and this carries %r"
                       % (statistic, of, _attr(target, "units"),
                          _attr(obj, "units")))

    # -- callables

    def _callables(self) -> None:
        group = self._group("callables")
        if group is None:
            return
        for member in self.members(group, "callables"):
            where = "callables/" + member.name
            self._name(member.name, where)
            if not isinstance(member.obj, h5py.Group):
                self.note(where, "a callable is a group, and this is a "
                                 "dataset")
                continue
            obj = member.obj
            if "type" not in _names(obj):
                self.error("E15", where, "a callable carries a type string")
            if "inputs" in _names(obj):
                self._inputs(_attr(obj, "inputs"), where)
            self.guarded(where, self._dictionary, obj, where, True)

    def _inputs(self, text: Any, where: str) -> None:
        """E45 and W19 over a callable's `inputs`."""
        if not isinstance(text, str):
            return
        for entry in text.split(" "):
            if not entry:
                continue
            if entry in self.parameters:
                p = self.parameters[entry]
                if _attr(p, "lower") is None or _attr(p, "upper") is None:
                    self.warn("W19", "parameters/" + entry,
                              "%s reads this parameter, which declares no "
                              "%s; a model's domain is declared by its "
                              "inputs' bounds" % (where, " and ".join(
                                  b for b in ("lower", "upper")
                                  if _attr(p, b) is None)))
                continue
            if entry in self.scalars:
                continue
            if entry.startswith(("node_arrays/", "cell_arrays/")):
                location, name = entry.split("/", 1)
                if name in self.mesh_arrays[location.split("_")[0]]:
                    continue
            self.error("E45", where, "inputs names %r, which is not a "
                                     "parameter, a scalar, or a field as "
                                     "node_arrays/<name> or "
                                     "cell_arrays/<name>" % entry)

    def _dictionary(self, group: h5py.Group, where: str, top_level: bool,
                    depth: int = 0) -> None:
        """E32 and E33 over one dictionary group."""
        if depth > limits.MAX_DEPTH:
            self.note(where, "this dictionary nests more than %d groups "
                             "deep, and is not checked further"
                      % limits.MAX_DEPTH)
            return
        for found in self.members(group, where):
            name, member = found.name, found.obj
            if name.startswith(RESERVED_PREFIX):
                continue
            path = "%s/%s" % (where, name)
            if top_level and name in _CALLABLE_ATTRS:
                self.error("E32", path, "type, repr and inputs are the "
                                        "container's attributes, so a "
                                        "dictionary may not use them at its "
                                        "top level")
            if not is_legal_name(name):
                self.error("E33", path, "a dictionary key is a legal "
                                        "netCDF-4 name")
            if isinstance(member, h5py.Group):
                self._dictionary(member, path, False, depth + 1)
                continue
            if h5safe.is_scale(member):
                continue
            if member.ndim == 0:
                self.error("E32", path, "a zero-dimensional array is written "
                                        "as an attribute, not as a dataset")
                continue
            if is_fixed_string(member.dtype):
                self._strings_of(member, path, "E32")
                continue
            if member.dtype.name not in ("int8", "int32", "int64",
                                         "float64"):
                self.error("E32", path, "%s is not a dtype a dictionary may "
                                        "hold" % member.dtype)
            elif member.dtype.byteorder == ">":
                self.error("E32", path, "a numeric array in a dictionary is "
                                        "little-endian")
        for name in _names(group):
            if name.startswith(RESERVED_PREFIX):
                continue
            if top_level and name in _CALLABLE_ATTRS:
                continue
            if not is_legal_name(name):
                self.error("E33", where, "the dictionary key %r is not a "
                                         "legal netCDF-4 name" % name)

    # -- the byte-level sweep

    def _bytes(self) -> None:
        """E19, E25, E26, E27, E29, E33, E42, E43 and W12 over every
        public object. `/private`, `/VTKHDF`, unknown groups and root
        objects with a role this reader does not know are outside the
        public byte rules."""
        self._object(self.f, "", named=True)
        stack = [(self.f, "", 0)]
        while stack:
            group, prefix, depth = stack.pop()
            if depth > limits.MAX_DEPTH:
                self.note(self.concept(prefix), "this group nests more "
                                                "than %d levels deep, and "
                                                "is not checked further"
                          % limits.MAX_DEPTH)
                continue
            for member in self.members(group, self.concept(prefix)):
                name, obj = member.name, member.obj
                path = "%s/%s" % (prefix, name)
                if _outside(prefix, name, obj, self.ignored):
                    continue
                self.visited += 1
                if self.visited > limits.MAX_OBJECTS:
                    self.note(self.concept(path), "this file holds more "
                                                  "than %d objects, and is "
                                                  "not checked further"
                              % limits.MAX_OBJECTS)
                    return
                named = _named_attrs(path)
                self.guarded(self.concept(path), self._object, obj, path,
                             named)
                if isinstance(obj, h5py.Group):
                    stack.append((obj, path, depth + 1))
                else:
                    self.guarded(self.concept(path), self._dataset, obj,
                                 path)

    def _object(self, obj: Any, path: str, named: bool) -> None:
        where = self.concept(path)
        for name in h5safe.attr_names(obj):
            if not is_legal_name(name):
                self.error("E33", where, "the attribute name %r is not a "
                                         "legal netCDF-4 name" % name)
            self.guarded(where, self._attr_encoding, obj, name, where,
                         named)

    def _attr_encoding(self, obj: Any, name: str, where: str,
                       named: bool) -> None:
        """E19 and E26 on one attribute."""
        attr = obj.attrs.get_id(name)
        kind = _ATTR_KIND.get(name) if named else None
        htype = attr.get_type()
        if tuple(attr.shape) and kind is not None:
            self.error("E19", where, "the attribute %s has the shape %s, "
                                     "and it has a scalar dataspace"
                       % (name, tuple(attr.shape)))
        if isinstance(htype, h5py.h5t.TypeStringID):
            if htype.is_variable_str():
                self.error("E19", where, "the attribute %s is a "
                                         "variable-length string" % name)
                return
            if htype.get_cset() != h5py.h5t.CSET_UTF8:
                self.error("E19", where, "the attribute %s is a string that "
                                         "is not UTF-8" % name)
            if htype.get_strpad() != h5py.h5t.STR_NULLPAD:
                self.error("E19", where, "the attribute %s is a string that "
                                         "is not NUL padded" % name)
            if kind is not None and kind != "string":
                self.error("E19", where, "the attribute %s is a %s and is "
                                         "stored as a string" % (name, kind))
            try:
                raw = obj.attrs[name]
            except Exception:
                return
            if isinstance(raw, np.ndarray) and raw.size:
                raw = raw.reshape(-1)[0]
            if isinstance(raw, bytes) and raw != NULL_SENTINEL:
                body = raw.rstrip(b"\x00")
                if b"\x00" in body:
                    self.error("E26", where, "the attribute %s holds a NUL "
                                             "byte outside its trailing "
                                             "padding" % name)
                try:
                    body.decode("utf-8")
                except UnicodeDecodeError:
                    self.error("E26", where, "the attribute %s is not valid "
                                             "UTF-8" % name)
            return
        if kind is None:
            return
        dtype = attr.dtype
        if kind == "string":
            self.error("E19", where, "the attribute %s is a string and is "
                                     "stored as %s" % (name, dtype))
        elif kind == "integer" and dtype != np.dtype("int64") and not (
                name == _SIGNIFICANT and dtype == np.dtype("int32")):
            self.error("E19", where, "the integer attribute %s is int64%s, "
                                     "and this is %s"
                       % (name, " or int32" if name == _SIGNIFICANT
                          else "", dtype))
        elif kind == "float":
            if dtype != np.dtype("float64"):
                self.error("E19", where, "the float attribute %s is "
                                         "float64, and this is %s"
                           % (name, dtype))
            elif not np.isfinite(np.asarray(obj.attrs[name])).all():
                self.error("E19", where, "the attribute %s declares a bound "
                                         "or a level and is finite" % name)

    def _dataset(self, dset: h5py.Dataset, path: str) -> None:
        where = self.concept(path)
        if h5safe.is_scale(dset):
            if "NAME" not in dset.attrs:
                self.error("E25", where, "this dimension scale carries CLASS "
                                         "and no NAME")
            if path.rsplit("/", 1)[-1] == "row" and dset.maxshape and \
                    dset.maxshape[0] is not None:
                self.error("E27", where, "row is an unlimited dimension in "
                                         "every file")
            order = h5safe.attr_creation_order(dset)
            if order is not None and order != SCALE_ATTR_ORDER:
                self.error("E42", where, "this dimension scale was created "
                                         "with attribute creation order %d "
                                         "where %d (tracked and indexed) is "
                                         "required" % (order,
                                                       SCALE_ATTR_ORDER))
            self._unlimited(dset, path, (path.rsplit("/", 1)[-1],))
            return
        attached = h5safe.scale_names(dset, self.scales)
        for axis, names in enumerate(attached):
            if len(names) != 1:
                self.error("E25", where, "axis %d carries %d dimension "
                                         "scales, and every axis carries "
                                         "exactly one" % (axis, len(names)))
        self._scale_names(dset, path, attached)
        disk = tuple(names[0] if len(names) == 1 else None
                     for names in attached)
        self._unlimited(dset, path, disk)
        self._filters(dset, where)
        leading = disk[0] if disk else None
        if leading == "row":
            if dset.chunks is None:
                self.error("E27", where, "a row-dimensioned dataset is "
                                         "chunked, because row is "
                                         "unlimited")
            else:
                self._chunk(dset, where)
        elif leading is not None and leading.startswith("group_"):
            if dset.chunks is None:
                self.error("E27", where, "a group-dimensioned dataset is "
                                         "chunked, because its group may "
                                         "grow")
            else:
                self._chunk(dset, where)

    def _unlimited(self, dset: h5py.Dataset, path: str,
                   dims: Sequence[str | None]) -> None:
        """E43: an unlimited dimension other than row, a group or a
        category table, or a zero-length dictionary axis."""
        for axis, limit in enumerate(dset.maxshape or ()):
            if limit is not None:
                continue
            name = dims[axis] if axis < len(dims) else None
            if name is not None and (name == "row" or name.startswith(
                    ("group_", "category_"))):
                continue
            if path.startswith("/callables/") and \
                    axis < len(dset.shape) and dset.shape[axis] == 0:
                continue
            empty = axis < len(dset.shape) and dset.shape[axis] == 0
            self.error("E43", self.concept(path),
                       "axis %d is unlimited, and %s is not row, a group or "
                       "a category table%s"
                       % (axis, "the dimension %s" % name if name else "it",
                          "; an axis of length zero can only be stored "
                          "unlimited, so a mesh needs at least one node and "
                          "one cell for its arrays" if empty else ""))

    def _filters(self, dset: h5py.Dataset, where: str) -> None:
        """E29: gzip at levels 1 to 9 and shuffle, and nothing else."""
        for code, _flags, values, name in h5safe.filters_of(dset):
            if code == _FILTER_SHUFFLE:
                continue
            if code == _FILTER_DEFLATE:
                level = int(values[0]) if values else 0
                if not 1 <= level <= 9:
                    self.error("E29", where, "gzip is allowed at levels 1 "
                                             "to 9, and this is %d" % level)
                if len(values) > 1:
                    self.error("E29", where, "gzip takes one client-data "
                                             "value and this has %d"
                               % len(values))
                continue
            self.error("E29", where, "the filter %d (%s) is not one of the "
                                     "two portable filters"
                       % (code, name or "unnamed"))

    def _scale_names(self, dset: h5py.Dataset, path: str,
                     attached: list[tuple[str, ...]]) -> None:
        """E25: the dimension name section 11 puts at each axis."""
        wanted = _wanted_dims(path, dset)
        if wanted is None:
            return
        got = [names[0] if len(names) == 1 else None for names in attached]
        for axis, (have, allowed) in enumerate(zip(got, wanted)):
            if have is None or allowed is None:
                continue
            if not allowed(have, dset.shape[axis]):
                self.error("E25", self.concept(path),
                           "axis %d carries the dimension %s, which is not "
                           "the name this axis takes" % (axis, have))

    def _chunk(self, dset: h5py.Dataset, where: str) -> None:
        """W12: decided from the file alone (section 12.3)."""
        chunks = tuple(dset.chunks)
        rest = tuple(int(n) for n in dset.shape[1:])
        whole = tuple(max(1, n) for n in rest)
        size = dset.dtype.itemsize
        bound = leading_bound(size, rest)
        if chunks[0] > bound:
            self.warn("W12", where, "the chunk holds %d entries along the "
                                    "leading axis where the default holds "
                                    "at most %d" % (chunks[0], bound))
            return
        if entry_bytes(size, rest) > CHUNK_TARGET and dset.ndim >= 3:
            block = site_block(size, max(1, rest[0]), rest[1])
            wanted = (block,) + whole[1:]
            if chunks[1:] != wanted:
                self.warn("W12", where, "an entry is larger than 256 KiB, "
                                        "so the default chunk takes the "
                                        "node or cell axis in blocks of %d "
                                        "and the rest whole, %s, and this "
                                        "takes %s"
                          % (block, wanted, chunks[1:]))
            return
        if chunks[1:] != whole:
            self.warn("W12", where, "the default chunk takes the axes after "
                                    "the leading one whole, %s, and this "
                                    "takes %s" % (whole, chunks[1:]))

    # -- small shared checks

    def _name(self, name: str, where: str) -> None:
        if not is_legal_name(name):
            self.error("E33", where, "%r is not a legal netCDF-4 name"
                       % name)
        elif name.startswith(RESERVED_PREFIX):
            self.error("E33", where, "%s is reserved for the container "
                                     "everywhere in the file"
                       % RESERVED_PREFIX)

    def _root_name(self, name: str, where: str) -> None:
        self._name(name, where)
        if is_reserved_root_name(name) and \
                not name.startswith(RESERVED_PREFIX):
            self.error("E33", where, "%r is reserved in the root" % name)

    def _unknown_attrs(self, obj: Any, where: str,
                       known: Sequence[str]) -> None:
        for name in _names(obj):
            if name not in known:
                self.warn("W11", where, "this reader does not know the "
                                        "attribute %s, and ignores it"
                          % name)

    def _units(self, obj: Any, where: str, required: bool) -> None:
        """E11: units present and parseable."""
        if "units" not in _names(obj):
            if required:
                self.error("E11", where, "units are required here")
            return
        text = read_attr(obj, "units")
        if not isinstance(text, str) or not is_parseable(text):
            self.error("E11", where, "the units string %r does not parse "
                                     "by the UDUNITS grammar" % (text,))

    def _source(self, obj: Any, where: str) -> bool:
        """E14, E30, E36, E39; True when a callable serves the slot."""
        attrs = _names(obj)
        if "source" not in attrs:
            self.error("E39", where, "a slot carries source")
            return False
        source = read_attr(obj, "source")
        if source == "data":
            if not isinstance(obj, h5py.Dataset):
                self.error("E30", where, "a slot whose source is data is a "
                                         "dataset, not a group")
            return False
        if not is_callable_source(source):
            self.error("E36", where, "source is data or callable:<id>, and "
                                     "this is %r" % (source,))
            return False
        if isinstance(obj, h5py.Dataset):
            self.error("E30", where, "a slot a callable serves is a group, "
                                     "not a dataset")
        identifier = source[len("callable:"):]
        holder = self._group("callables")
        if holder is None or identifier not in holder:
            self.error("E14", where, "the file holds no callable called %r"
                       % identifier)
        if "output" not in attrs:
            self.error("E39", where, "a slot a callable serves names the "
                                     "output that fills it")
        return True

    def _statistic(self, obj: Any, where: str, served: bool) -> None:
        """E02 and E12 that a slot's own attributes decide."""
        attrs = _names(obj)
        statistic = _attr(obj, "statistic") if "statistic" in attrs \
            else None
        wrt = "with_respect_to" in attrs
        if statistic is not None and statistic not in STATISTICS:
            self.error("E02", where, "%r is not a statistic; a relation is "
                                     "band or std" % (statistic,))
            return
        if statistic is not None and wrt:
            self.error("E12", where, "a slot carries statistic or "
                                     "with_respect_to, not both")
        if (statistic is not None or wrt) and "of" not in attrs:
            self.error("E12", where, "a relation names the result it is "
                                     "about with of")
        if "of" in attrs and statistic is None and not wrt:
            self.error("E12", where, "of names the base of a relation, and "
                                     "this slot carries neither statistic "
                                     "nor with_respect_to")
        if statistic != "band" and ("level" in attrs or "method" in attrs):
            self.error("E12", where, "level and method belong to a band")
        if statistic == "std" and served:
            self.error("E12", where, "a std is stored, never served")
        if statistic == "band" and not served:
            level = _attr(obj, "level")
            if "level" not in attrs:
                self.error("E12", where, "a band states its coverage with "
                                         "level")
            elif isinstance(level, float) and not 0.0 < level < 1.0:
                self.error("E12", where, "level is a coverage in (0, 1), "
                                         "and this is %r" % level)
            if "method" not in attrs:
                self.error("E12", where, "a band says how it was made with "
                                         "method")

    def _rows(self, dset: h5py.Dataset, where: str) -> None:
        """E16: one-dimensional where the root needs it, and the
        leading length against the row count."""
        if where.startswith(("parameters/", "labels/", "scalars/")) and \
                dset.ndim != 1:
            self.error("E16", where, "a row dataset in the root has exactly "
                                     "one dimension, and this has %d"
                       % dset.ndim)
        if dset.ndim and dset.shape[0] != self.n_rows:
            self.error("E16", where, "this holds %d rows where the file has "
                                     "%d" % (dset.shape[0], self.n_rows))

    def _finite(self, dset: h5py.Dataset, where: str) -> None:
        """W03: non-finite values in a stored result."""
        if dset.dtype.kind != "f" or not dset.size:
            return
        values = self.values(dset, where)
        if values is None or values.dtype.kind != "f":
            return
        leading = _logical(dset, self.scales)
        said = w03(values, leading[0] if leading and leading[0]
                   else "index")
        if said:
            self.warn("W03", where, said)

    def _band(self, dset: h5py.Dataset, where: str) -> None:
        """W16: a negative value in a band."""
        if _attr(dset, "statistic") != "band" or dset.dtype.kind != "f" \
                or not dset.size:
            return
        values = self.values(dset, where)
        if values is None:
            return
        leading = _logical(dset, self.scales)
        said = w16(values, leading[0] if leading and leading[0]
                   else "index")
        if said:
            self.warn("W16", where, said)

    def _private(self) -> None:
        """E18: public information missing from a file that carries
        /private, reported beside the rule that found it."""
        if "private" not in self.root:
            return
        missing: dict[str, set[str]] = {}
        for found in self.report.errors:
            if found.rule in _MISSING_PUBLIC:
                missing.setdefault(found.path, set()).add(found.rule)
        for where, rules in missing.items():
            self.error("E18", where, "public information is missing here "
                                     "(%s) and the file carries a private "
                                     "group; a writer must not put public "
                                     "information only there"
                       % ", ".join(sorted(rules)))


# -------------------------------------------------------------- helpers

def _once(into: list[Finding], rule: str, where: str,
          message: str) -> None:
    """One finding per rule per object."""
    for found in into:
        if found.rule == rule and found.path == where:
            return
    into.append(Finding(rule, where, message))


def _join(where: str, name: str) -> str:
    return "%s/%s" % (where, name) if where else name


def _utf8(names: Any) -> list[str]:
    return sorted(names, key=lambda n: n.encode("utf-8", "replace"))


def _names(obj: Any) -> list[str]:
    return [n for n in obj.attrs if n not in MACHINERY]


def _attr(obj: Any, name: str) -> Any:
    if name not in obj.attrs or name in MACHINERY:
        return None
    return read_attr(obj, name)


def _plain(value: Any) -> Any:
    return value.item() if isinstance(value, np.generic) else value


def _is_relation(obj: Any) -> bool:
    names = _names(obj)
    return "statistic" in names or "with_respect_to" in names


def _count(many: int, singular: str, plural: str) -> str:
    return singular if many == 1 else "%d %s" % (many, plural)


def _at(dimension: str, indices: Any) -> str:
    listed = [int(i) for i in list(indices)[:3]]
    text = "at %s %s" % (dimension, ", ".join(str(i) for i in listed))
    if len(indices) > len(listed):
        text += " and %d more" % (len(indices) - len(listed))
    return text


def _named(table: Any, value: Any) -> str:
    at = int(value)
    if table is not None and 0 <= at < len(table):
        return str(table[at])
    return str(at)


def w01(codes: np.ndarray, split: np.ndarray, group: str, table: Any,
        kind: str = "unit of generalisation") -> str | None:
    """W01: a split that divides a unit of generalisation or a run."""
    leaked = [one for one in np.unique(codes)
              if len(np.unique(split[codes == one])) > 1]
    if not leaked:
        return None
    named = [_named(table, one) for one in leaked]
    noun = "%s %s" % (kind, group)
    if len(named) == 1:
        return ("the rows of %s %s are on both sides of the split"
                % (noun, named[0]))
    return ("the rows of %d of %s (%s%s) are on both sides of the split"
            % (len(named), noun, ", ".join(named[:3]),
               " and %d more" % (len(named) - 3) if len(named) > 3 else ""))


def w02(values: np.ndarray, table: Any) -> str | None:
    """W02: rows whose status is not converged."""
    bad = [row for row, value in enumerate(values)
           if 0 <= int(value) < len(table)
           and table[int(value)] != "converged"]
    if not bad:
        return None
    return ("%s of %d with a status other than converged (the first is "
            "%r), %s; the recommended words are %s, and a row that is not "
            "converged is not fit to use unless asked for"
            % (_count(len(bad), "one row", "rows"), len(values),
               table[int(values[bad[0]])], _at("row", bad),
               ", ".join(STATUS_WORDS)))


def w03(values: np.ndarray, axis: str) -> str | None:
    """W03: non-finite values, with where they are."""
    if values.dtype.kind != "f" or not values.size:
        return None
    bad = ~np.isfinite(values)
    if not bad.any():
        return None
    if values.ndim == 0:
        return "the value is not finite"
    rows = sorted({int(at[0]) for at in np.argwhere(bad)})
    return ("%s, which is how this format spells a missing value, %s"
            % (_count(int(bad.sum()), "a non-finite value",
                      "non-finite values"), _at(axis, rows)))


def w04(values: np.ndarray, lower: Any, upper: Any) -> str | None:
    """W04: parameter values outside the declared bounds."""
    outside = np.zeros(values.shape, dtype=bool)
    if lower is not None:
        outside |= values < lower
    if upper is not None:
        outside |= values > upper
    if values.dtype.kind == "f":
        outside &= np.isfinite(values)
    if not outside.any():
        return None
    rows = sorted({int(at[0]) for at in np.argwhere(outside)})
    return ("%s outside the declared bounds [%s, %s], %s"
            % (_count(int(outside.sum()), "a value", "values"), lower,
               upper, _at("row", rows)))


def w16(values: np.ndarray, axis: str) -> str | None:
    """W16: negative values in a band, which is a half-width."""
    if values.dtype.kind != "f" or not values.size:
        return None
    bad = values < 0
    if not bad.any():
        return None
    if values.ndim == 0:
        return "the band is below zero; a band is a half-width"
    rows = sorted({int(at[0]) for at in np.argwhere(bad)})
    return ("%s below zero in a band, which is a half-width and is never "
            "negative, %s" % (_count(int(bad.sum()), "a value", "values"),
                              _at(axis, rows)))


def w18(times: np.ndarray, codes: np.ndarray, table: Any) -> str | None:
    """W18: two rows of one run at the same time."""
    runs = []
    for one in np.unique(codes):
        mine = times[codes == one]
        if mine.size != np.unique(mine).size:
            runs.append(_named(table, one))
    if not runs:
        return None
    return ("%s two rows at the same time (%s%s); a run holds one row per "
            "time" % (_count(len(runs), "one run has", "runs have"),
                      ", ".join(runs[:3]),
                      " and %d more" % (len(runs) - 3) if len(runs) > 3
                      else ""))


def _logical(dset: h5py.Dataset,
             scales: Mapping[int, str]) -> tuple[str, ...]:
    from .names import logical_dimension
    return tuple(logical_dimension(names[0]) if len(names) == 1 else ""
                 for names in h5safe.scale_names(dset, scales))


def _outside(prefix: str, name: str, obj: Any, ignored: set[str]) -> bool:
    """True for what the public byte rules do not reach: /private,
    /VTKHDF, a group this version does not know, and a root object
    with a role it does not know."""
    if prefix == "":
        if name in ("private", "VTKHDF") or name in ignored:
            return True
        if isinstance(obj, h5py.Group):
            if name in _ROOT_GROUPS:
                return False
            return "role" not in _names(obj)
        # A scale the format does not name serves only objects this
        # reader ignores; a public dataset attached to it is E25.
        return h5safe.is_scale(obj) and not (
            name == "row" or name.startswith(("component_", "group_",
                                              "category_")))
    if prefix == "/mesh":
        return name not in _MESH_MEMBERS
    return False


def _named_attrs(path: str) -> bool:
    """Whether the attributes of the object at `path` are the ones the
    specification names (and so have one encoding each), rather than
    free-form: notes, and a callable's dictionary below its group."""
    parts = path.strip("/").split("/")
    if parts[0] == "notes":
        return False
    return not (parts[0] == "callables" and len(parts) > 2)


def _exact(name: str) -> Any:
    return lambda have, length: have == name


def _component(have: str, length: int) -> bool:
    return have == "component_%d" % length


def _leading(have: str, length: int) -> bool:
    return have == "row" or have.startswith("group_")


def _wanted_dims(path: str, dset: h5py.Dataset) -> Any:
    """What each axis of a dataset may be called (section 11)."""
    parts = path.strip("/").split("/")
    if len(parts) == 1:
        return [_exact("row")] if dset.ndim == 1 else None
    if parts[0] == "categories" and len(parts) == 2:
        return [_exact("category_" + parts[1])]
    if parts[0] == "callables":
        name = parts[-1]
        return [(lambda have, length, at=at, name=name:
                 have == "%s%s_d%d" % (RESERVED_PREFIX, name, at))
                for at in range(dset.ndim)]
    if parts[0] != "mesh":
        return None
    last = parts[-1]
    if len(parts) == 2:
        if last == "cell_types":
            return [_exact("cell")]
        if last == "cell_offsets":
            return [_exact("cell_plus_one")]
        if last == "cell_connectivity":
            return [_exact("index")]
        if last != "coordinates":
            return None
    location = "cell" if "cell_arrays" in parts else "node"
    if dset.ndim < 2:
        return None
    return [_leading] * (dset.ndim - 2) + [_exact(location), _component]


def _is_iso_utc(text: Any) -> bool:
    """W14: an ISO 8601 timestamp in UTC."""
    if not isinstance(text, str):
        return False
    body = text.strip()
    if body.endswith("Z"):
        body = body[:-1]
    elif body.endswith("+00:00"):
        body = body[:-len("+00:00")]
    else:
        return False
    import datetime
    for form in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f",
                 "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            datetime.datetime.strptime(body, form)
            return True
        except ValueError:
            continue
    return False


# Rule identifiers this validator may emit, for the record.
EMITTED = ("E01", "E02", "E03", "E04", "E05", "E08", "E10", "E11", "E12",
           "E14", "E15", "E16", "E17", "E18", "E19", "E20", "E21", "E22",
           "E23", "E24", "E25", "E26", "E27", "E29", "E30", "E31", "E32",
           "E33", "E34", "E35", "E36", "E38", "E39", "E40", "E41", "E42",
           "E43", "E45", "E47", "E48", "E49", "W01", "W02", "W03", "W04",
           "W07", "W08", "W11", "W12", "W13", "W14", "W16", "W18", "W19")

"""Reading a version 1 file.

`read(path)` returns a lazy `Dataset` handle: opening reads
attributes, dataspaces, link types, dimension-scale structure and the
category tables, and nothing else. Values are read when asked for,
and only the part asked for. `lazy=False` reads every value at once
and closes the file.

A file is untrusted input. The reader follows no soft or external
link, applies the limits in `mestra.limits`, and reports what it could
not read on `dataset._problems`. A strict read (the default) refuses a
file that breaks a structural rule; a semantic fault never stops a
read. A version 0 file is refused with the rule E01 and the name of
the upgrade.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import h5py
import numpy as np

from . import h5safe, limits, opaque
from .callables import OpaqueCallable, callable_from_dict
from .codec import RESERVED, decode_dict
from .encoding import (
    decode_string,
    is_fixed_string,
    read_attr,
    string_length,
)
from .errors import Finding, MestraError
from .model import (
    FORMAT,
    LABEL_ROLES,
    PARAMETER_ROLES,
    CategoryTable,
    Dataset,
    FileSource,
    Label,
    MemorySource,
    Mesh,
    Parameter,
    Slot,
    _Handle,
)
from .names import logical_dimension

__all__ = ["read", "REFUSED", "ROOT_GROUPS"]

#: The rules under which this reader cannot vouch for what it would
#: return, so a strict `read` refuses a file that breaks one of them.
#: Everything else is the file describing itself badly, and the values
#: still mean what they say.
REFUSED = ("E01", "E16", "E19", "E25", "E26", "E29", "E30", "E40",
           "E41")

#: The named groups of the root (section 11).
ROOT_GROUPS = ("categories", "mesh", "callables", "notes", "private",
               "VTKHDF")

_ROOT_ATTRS = ("format", "writer", "created", "generalisation_group",
               "title", "license", "references", "source")
_PARAMETER_ATTRS = ("role", "units", "lower", "upper", "run_group")
_LABEL_ATTRS = ("role", "category")
_SLOT_ATTRS = ("role", "units", "varies", "components", "source",
               "coordinates", "category", "output", "of", "statistic",
               "level", "method", "with_respect_to",
               "_QuantizeBitRoundNumberOfSignificantBits")
_MESH_ATTRS = ("kind", "n_nodes", "n_cells", "support_id")
_MESH_MEMBERS = ("node", "cell", "cell_plus_one", "index", "cell_types",
                 "cell_offsets", "cell_connectivity", "coordinates",
                 "node_arrays", "cell_arrays")


def read(path: str, lazy: bool = True, strict: bool = True) -> Dataset:
    """Open a file and return the dataset it holds.

    With `lazy` (the default) values stay in the file until asked for
    and the file stays open: close it with `dataset.close()`, or use
    the dataset as a context manager. Refusals are `MestraError` with
    the rule: E01 for a file that is not version 1 (a version 0 file
    names `mestra.upgrade`), E40 for a link this reader does not
    follow, E41 for an object it could not read, and the other rules
    of `REFUSED`. `strict=False` takes what could be read, with the
    findings on `dataset._problems`.
    """
    handle = h5safe.open_file(str(path))
    if strict:
        _refuse(handle, str(path))
    holder = _Handle(handle)
    try:
        dataset = _read(handle, holder, lazy)
    except MestraError:
        handle.close()
        raise
    except Exception as exc:
        handle.close()
        raise MestraError(
            "E41", "this file could not be read: %s" % h5safe._brief(exc),
            str(path)) from None
    dataset.path = str(path)
    dataset._handle = holder
    if not lazy:
        dataset.callables._read_all()
        holder.close()
    return dataset


def _refuse(handle: h5py.File, path: str) -> None:
    """Refuse a file this reader cannot vouch for, deciding it from
    the metadata a lazy open reads."""
    from .validator import scan
    report = scan(handle, limit=limits.MAX_OPEN_ELEMENTS,
                  tables_only=True)
    bad = [f for f in report.errors if f.rule in REFUSED]
    if bad:
        handle.close()
        raise MestraError(
            bad[0].rule, "%s. This file breaks %s, so this reader cannot "
            "vouch for what it would return; read it with strict=False "
            "to take what there is"
            % (bad[0].message, ", ".join(sorted({f.rule for f in bad}))),
            bad[0].path or path)


def version_message(found: Any) -> str:
    """What E01 says about a file's `format`."""
    if found == "mestra/0":
        return ("this is a version 0 file; this reader reads %s. Convert "
                "it with mestra.upgrade(src, dst), or `mestra upgrade "
                "SRC DST`, which writes a new file and leaves this one as "
                "it is" % FORMAT)
    return "this reader accepts %s and the file says %r" % (FORMAT, found)


def _read(f: h5py.File, holder: _Handle, lazy: bool) -> Dataset:
    ds = Dataset(writer="", created="")
    root = {m.name: m for m in h5safe.members(f)}
    names = h5safe.attr_names(f)
    if "format" not in names:
        raise MestraError("E01", "the root attribute format is missing",
                          "")
    ds.format = read_attr(f, "format")
    if ds.format != FORMAT:
        raise MestraError("E01", version_message(ds.format), "")
    ds.writer = _text(f, "writer") or ""
    ds.created = _text(f, "created") or ""
    for name in ("generalisation_group", "title", "license",
                 "references", "source"):
        if name in names:
            setattr(ds, name, read_attr(f, name))
    scales = h5safe.scale_index(f)
    reader = _Reader(ds, holder, lazy, scales)
    ds._extra = reader.extra(f, _ROOT_ATTRS, "")
    found = root.get("row")
    if found is not None and isinstance(found.obj, h5py.Dataset) and \
            found.obj.shape:
        ds._row_count = int(found.obj.shape[0])
    reader.categories(root.get("categories"))
    for name, member in root.items():
        reader.root_member(name, member)
    if ds._row_count is None:
        ds._row_count = ds.row_count
    reader.mesh(root.get("mesh"))
    reader.callables(root.get("callables"))
    reader.notes(root.get("notes"))
    return ds


def _text(obj: Any, name: str) -> str | None:
    value = read_attr(obj, name) if name in h5safe.attr_names(obj) \
        else None
    return value if isinstance(value, str) else None


class _Reader:
    """One open of one file."""

    def __init__(self, ds: Dataset, holder: _Handle, lazy: bool,
                 scales: Mapping[int, str]) -> None:
        self.ds = ds
        self.holder = holder
        self.lazy = lazy
        self.scales = scales

    def problem(self, where: str, message: str, rule: str = "E41",
                lossy: bool = False) -> None:
        self.ds._problems.append(Finding(rule, where, message))
        if lossy:
            self.ds._lossy.append(where)

    def unusable(self, where: str, member: h5safe.Member) -> None:
        self.problem(where, member.problem or "this member cannot be read",
                     member.rule, lossy=member.kind == h5safe.EXTERNAL)

    def extra(self, obj: Any, known: Any, where: str) -> dict[str, Any]:
        """The attributes of `obj` this reader does not know, exactly as
        stored, so that a rewrite puts them back unchanged."""
        return opaque.capture_attributes(obj, known, where,
                                         self.ds._problems, self.ds._lossy)

    def source(self, path: str, dset: h5py.Dataset) -> Any:
        made = FileSource(self.holder, path, dset.shape, dset.dtype,
                          is_fixed_string(dset.dtype))
        if self.lazy:
            return made
        return MemorySource(made.read())

    def dims(self, dset: h5py.Dataset,
             fallback: tuple[str, ...]) -> tuple[str, ...]:
        names = h5safe.scale_names(dset, self.scales)
        if len(names) != dset.ndim or any(len(a) != 1 for a in names):
            return fallback
        return tuple(logical_dimension(a[0]) for a in names)

    # -- the root

    def categories(self, found: h5safe.Member | None) -> None:
        group = self.group(found, "categories")
        if group is None:
            return
        for member in h5safe.members(group):
            where = "categories/" + member.name
            if not member.usable:
                self.unusable(where, member)
                continue
            if not isinstance(member.obj, h5py.Dataset):
                self.problem(where, "a category table is a dataset, and "
                                    "this is a group")
                continue
            try:
                values = h5safe.read_values(member.obj, where)
            except MestraError as exc:
                self.problem(where, exc.message, lossy=True)
                continue
            entries = [decode_string(v) if isinstance(v, bytes) else str(v)
                       for v in np.asarray(values).reshape(-1)]
            self.ds.categories[member.name] = CategoryTable(
                entries, itemsize=string_length(member.obj.dtype),
                extra=self.extra(member.obj, (), where))

    def group(self, found: h5safe.Member | None,
              name: str) -> h5py.Group | None:
        if found is None:
            return None
        if not found.usable:
            self.unusable(name, found)
            return None
        if not isinstance(found.obj, h5py.Group):
            self.problem(name, "this is a dataset where the format has a "
                               "group, so it is not read")
            return None
        self.ds._present.add(name)
        if name in ("categories", "callables"):
            kept = self.extra(found.obj, (), name)
            if kept:
                self.ds._group_extra[name] = kept
        return found.obj

    def root_member(self, name: str, member: h5safe.Member) -> None:
        ds = self.ds
        if name in ROOT_GROUPS and name not in ("private", "VTKHDF"):
            return
        if not member.usable:
            self.unusable(name, member)
            return
        obj = member.obj
        if isinstance(obj, h5py.Dataset) and h5safe.is_scale(obj):
            ds._scales[("", name)] = _scale_info(obj)
            kept = self.extra(obj, (), name)
            if kept:
                ds._scale_extra[("", name)] = kept
            return
        if name in ("private", "VTKHDF") or (
                isinstance(obj, h5py.Group)
                and "role" not in h5safe.attr_names(obj)):
            if isinstance(obj, h5py.Group):
                ds._opaque[name] = opaque.capture(
                    obj, "/" + name, 0, ds._problems, ds._lossy, self.lazy,
                    self.scales)
            else:
                ds._unknown[name] = opaque.capture_member(
                    obj, "/" + name, ds._problems, ds._lossy, self.lazy,
                    self.scales)
            return
        attrs = h5safe.attr_names(obj)
        role = read_attr(obj, "role") if "role" in attrs else None
        if role in PARAMETER_ROLES and isinstance(obj, h5py.Dataset):
            ds.parameters[name] = Parameter(
                name, role, units=_get(obj, "units"),
                lower=_get(obj, "lower"), upper=_get(obj, "upper"),
                run_group=_get(obj, "run_group"),
                data=self.source("/" + name, obj),
                extra=self.extra(obj, _PARAMETER_ATTRS, "parameters/" + name))
        elif role in LABEL_ROLES and isinstance(obj, h5py.Dataset):
            ds.labels[name] = Label(
                name, role, category=_get(obj, "category"),
                data=self.source("/" + name, obj),
                extra=self.extra(obj, _LABEL_ATTRS, "labels/" + name),
                dataset=ds)
        elif role == "scalar":
            ds.scalars[name] = self.slot(obj, name, "/" + name, "row")
        else:
            # A role this reader does not know (W11), or an object of
            # the wrong kind for its role: kept whole for a rewrite.
            ds._unknown[name] = opaque.capture_member(
                obj, "/" + name, ds._problems, ds._lossy, self.lazy,
                self.scales)

    def slot(self, obj: Any, name: str, path: str,
             location: str) -> Slot:
        got = {key: _get(obj, key) for key in _SLOT_ATTRS
               if key in h5safe.attr_names(obj)}
        components = got.get("components")
        role = got.get("role")
        varies = got.get("varies")
        if not isinstance(varies, str):
            varies = "row" if location == "row" else "none"
        source = got.get("source")
        if not isinstance(source, str):
            source = "data"
        slot = Slot(
            name, location=location,
            role=role if isinstance(role, str) else "",
            units=got.get("units"), varies=varies,
            components=components if isinstance(components, int)
            else None,
            source=source,
            output=got.get("output"), statistic=got.get("statistic"),
            of=got.get("of"), level=got.get("level"),
            method=got.get("method"),
            with_respect_to=got.get("with_respect_to"),
            significant_bits=got.get(
                "_QuantizeBitRoundNumberOfSignificantBits"),
            category=got.get("category"),
            coordinates_attr=got.get("coordinates"),
            extra=self.extra(obj, _SLOT_ATTRS, path.lstrip("/")))
        slot._dataset = self.ds
        if isinstance(obj, h5py.Dataset):
            slot._data = self.source(path, obj)
            slot._dims = self.dims(obj, slot.dims)
        return slot

    # -- the mesh

    def mesh(self, found: h5safe.Member | None) -> None:
        group = self.group(found, "mesh")
        if group is None:
            return
        ds = self.ds
        attrs = h5safe.attr_names(group)
        n_nodes = _get(group, "n_nodes")
        n_cells = _get(group, "n_cells")
        kind = _get(group, "kind")
        mesh = Mesh(kind if isinstance(kind, str) else None,
                    n_nodes=n_nodes if isinstance(n_nodes, int) else 0,
                    n_cells=n_cells if isinstance(n_cells, int) else 0,
                    stored_support_id=_get(group, "support_id")
                    if "support_id" in attrs else None,
                    extra=self.extra(group, _MESH_ATTRS, "mesh"))
        mesh._dataset = ds
        ds.mesh = mesh
        inside = {m.name: m for m in h5safe.members(group)}
        for which in ("cell_types", "cell_offsets", "cell_connectivity"):
            member = inside.get(which)
            if member is None:
                continue
            if not member.usable or not isinstance(member.obj,
                                                   h5py.Dataset):
                self.problem("mesh/" + which,
                             member.problem or "this is not a dataset",
                             member.rule)
                continue
            mesh._cells[which] = self.source("/mesh/" + which, member.obj)
            kept = self.extra(member.obj, (), "mesh/" + which)
            if kept:
                mesh._cell_extra[which] = kept
        member = inside.get("coordinates")
        if member is not None:
            if member.usable:
                mesh.coordinates = self.slot(member.obj, "coordinates",
                                             "/mesh/coordinates", "node")
            else:
                self.unusable("mesh/coordinates", member)
        for which, location, into in (
                ("node_arrays", "node", mesh.node_arrays),
                ("cell_arrays", "cell", mesh.cell_arrays)):
            holder = inside.get(which)
            if holder is None:
                continue
            if not holder.usable or not isinstance(holder.obj,
                                                   h5py.Group):
                self.problem("mesh/" + which,
                             holder.problem or "this is not a group",
                             holder.rule)
                continue
            mesh._present.add(which)
            kept = self.extra(holder.obj, (), "mesh/" + which)
            if kept:
                mesh._group_extra[which] = kept
            for array in h5safe.members(holder.obj):
                where = "mesh/%s/%s" % (which, array.name)
                if not array.usable:
                    self.unusable(where, array)
                    continue
                dict.__setitem__(into, array.name, self.slot(
                    array.obj, array.name, "/" + where, location))
        for name, member in inside.items():
            if member.usable and isinstance(member.obj, h5py.Dataset) \
                    and h5safe.is_scale(member.obj):
                ds._scales[("mesh", name)] = _scale_info(member.obj)
                kept = self.extra(member.obj, (), "mesh/" + name)
                if kept:
                    ds._scale_extra[("mesh", name)] = kept
            if name in _MESH_MEMBERS:
                continue
            where = "mesh/" + name
            if not member.usable:
                self.unusable(where, member)
                continue
            if isinstance(member.obj, h5py.Group):
                mesh._opaque[name] = opaque.capture(
                    member.obj, "/" + where, 0, ds._problems, ds._lossy,
                    self.lazy, self.scales)
            elif not h5safe.is_scale(member.obj):
                mesh._unknown[name] = opaque.capture_member(
                    member.obj, "/" + where, ds._problems, ds._lossy,
                    self.lazy, self.scales)

    # -- callables and notes

    def callables(self, found: h5safe.Member | None) -> None:
        group = self.group(found, "callables")
        if group is None:
            return
        ds = self.ds
        for member in h5safe.members(group):
            where = "callables/" + member.name
            if not member.usable:
                self.unusable(where, member)
                continue
            if not isinstance(member.obj, h5py.Group):
                self.problem(where, "a callable is a group, and this is a "
                                    "dataset")
                continue
            kind = _get(member.obj, "type")
            line = _get(member.obj, "repr")
            declared = _get(member.obj, "inputs")
            inputs = frozenset(declared.split()) \
                if isinstance(declared, str) else None
            ds._callable_inputs[member.name] = inputs
            ds.callables._defer(member.name, _build_callable(
                ds, where, member.obj, kind if isinstance(kind, str)
                else "", line if isinstance(line, str) else None, inputs,
                self.holder))

    def notes(self, found: h5safe.Member | None) -> None:
        group = self.group(found, "notes")
        if group is None:
            return
        for name in h5safe.attr_names(group):
            try:
                raw = group.attrs[name]
            except Exception:
                self.problem("notes", "the note %s cannot be read" % name)
                continue
            if isinstance(raw, np.ndarray) and raw.ndim == 1 and \
                    raw.dtype.kind in "iuf":
                dict.__setitem__(self.ds.notes, name, np.array(raw))
            else:
                dict.__setitem__(self.ds.notes, name,
                                 read_attr(group, name))


def _scale_info(dset: h5py.Dataset) -> tuple[int, bool]:
    """A dimension scale's length, and whether it is unlimited."""
    try:
        length = int(dset.shape[0]) if dset.shape else 0
        unlimited = bool(dset.maxshape) and dset.maxshape[0] is None
    except Exception:                                   # pragma: no cover
        return 0, False
    return length, unlimited


def _get(obj: Any, name: str) -> Any:
    if name in h5safe.attr_names(obj):
        return read_attr(obj, name)
    return None


def _build_callable(ds: Dataset, where: str, group: h5py.Group,
                    kind: str, line: str | None,
                    inputs: frozenset[str] | None,
                    holder: _Handle) -> Any:
    """What `Dataset.callables` runs the first time it is asked for
    this callable: decode the dictionary and hand it to its type. The
    dictionary is in the file, so a closed dataset refuses, as every
    other read of a closed dataset does."""
    def build() -> Any:
        if holder.file is None:
            raise MestraError(
                "", "this dataset has been closed; read it again, or read "
                "with lazy=False to keep the values", where)
        trouble: list[Finding] = []
        body = decode_dict(group, problems=trouble, reserved=RESERVED)
        if trouble:
            ds._problems.extend(trouble)
            ds._lossy.append(where)
        try:
            made = callable_from_dict(kind, body, line, inputs)
        except MestraError as exc:
            ds._problems.append(Finding(
                "E41", where, "this callable's dictionary does not fit "
                "its type: %s" % exc.message))
            made = OpaqueCallable(kind, body, line, inputs)
        return made
    return build

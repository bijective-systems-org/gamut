"""Writing a version 1 file.

`write(dataset, path)` lays the file out as the specification's
section 11 gives it: the run table in the root, one `/mesh` group,
`/categories`, `/callables`, `/notes` and whatever the dataset carries
that this version does not know. Every dataset is laid out with the
defaults of section 12, whatever the file it was read from used:
chunks by the rule of section 12.3, shuffle and gzip at level 1 on
every dataset with a `row` or group axis, fixed-length strings no
wider than their longest element. So `write(read(p), q)` compacts a
file that appends have grown.

The file is staged beside the destination, validated, and published
by an atomic replace only when it validates; a refusal or a failure
leaves an existing destination untouched. Values that a lazy dataset
still holds in its file are copied a block of rows at a time and are
never held whole.
"""

from __future__ import annotations

import os
import stat
import tempfile
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import h5py
import numpy as np

from . import opaque
from .codec import encode_dict
from .encoding import (
    CHUNK_TARGET,
    default_chunks,
    encode_strings,
    make_scale,
    string_dtype,
    write_attr,
    write_float_attr,
    write_int_attr,
    write_string_attr,
)
from .errors import MestraError
from .model import (
    Dataset,
    Label,
    MemorySource,
    Mesh,
    Parameter,
    Slot,
)
from .names import disk_dimension

__all__ = ["write", "coordinates_attribute", "SIGNIFICANT_BITS"]

#: The bytes one streamed block of rows aims at.
_BLOCK_BYTES = 16 * 1024 * 1024

#: The attribute netCDF-C writes for BitRound, and this format reads.
SIGNIFICANT_BITS = "_QuantizeBitRoundNumberOfSignificantBits"

#: The three cell datasets, the scale of each, and its dtype.
_CELLS = (("cell_types", "cell", "<u1"),
          ("cell_offsets", "cell_plus_one", "<i8"),
          ("cell_connectivity", "index", "<i8"))

_PARAMETER_ORDER = ("role", "units", "lower", "upper", "run_group")
_LABEL_ORDER = ("role", "category")
_SLOT_ORDER = ("role", "units", "varies", "components", "source",
               "coordinates", "category", "output", "of", "statistic",
               "level", "method", "with_respect_to")


def write(dataset: Dataset, path: str, check: bool = True) -> None:
    """Write `dataset` to `path` as a version 1 file.

    The file is staged beside the destination and, unless `check` is
    false, validated there; any error refuses the write with the
    findings and leaves an existing destination as it was. Warnings
    do not stop a write. `check=False` publishes whatever was staged,
    which is how a test makes a file to be refused.
    """
    dataset.callables.read_all()
    for captured in list(dataset.opaque.values()):
        opaque.read_all(captured)
    for kind, body in dataset.unknown.values():
        opaque.read_member(kind, body)
    if dataset.mesh is not None:
        for captured in dataset.mesh.opaque.values():
            opaque.read_all(captured)
    if dataset.lossy:
        raise MestraError(
            "E41", "this dataset was read from a file with parts that "
            "could not be copied (%s), so writing it would lose them"
            % ", ".join(sorted(dataset.lossy)[:4]), str(path))
    target = Path(path)
    _refuse_a_destination_that_cannot_take_a_file(str(path), target)
    _refuse_unwritable_names(dataset)
    try:
        mode = stat.S_IMODE(target.stat().st_mode)
    except FileNotFoundError:
        mode = None
    with tempfile.TemporaryDirectory(prefix=".%s.mestra-" % target.name,
                                     dir=target.parent) as directory:
        staged = Path(directory) / "data.mes"
        with h5py.File(staged, "w") as f:
            _write(dataset, f)
        if check:
            _refuse_what_the_validator_finds(str(staged), str(path))
        if mode is not None:
            staged.chmod(mode)
        os.replace(staged, target)


def _refuse_a_destination_that_cannot_take_a_file(path: str,
                                                  target: Path) -> None:
    """Staging and publishing happen in the destination's directory,
    so a destination that cannot take a file is refused first."""
    if not path:
        raise MestraError("", "path is empty; pass the name of the file "
                              "to write", path)
    if target.is_dir():
        raise MestraError("", "path names a directory, which a file "
                              "cannot replace; pass a file name", path)
    parent = target.parent
    if not parent.is_dir():
        raise MestraError("", "the directory %s does not exist; the file "
                              "is staged and published there, so create "
                              "it first" % parent, path)
    if not os.access(parent, os.W_OK | os.X_OK):
        raise MestraError("", "the directory %s is not writable; the file "
                              "is staged and published there" % parent,
                          path)


def _producer_names(ds: Dataset) -> Iterable[tuple[str, Any]]:
    for name in ds.categories:
        yield "categories/" + str(name), name
    for kind, group in (("parameters", ds.parameters),
                        ("labels", ds.labels), ("scalars", ds.scalars)):
        for name in dict.keys(group):
            yield "%s/%s" % (kind, name), name
    for name in dict.keys(ds.callables):
        yield "callables/" + str(name), name
    if ds.mesh is not None:
        for location, group in (("node", ds.mesh.node_arrays),
                                ("cell", ds.mesh.cell_arrays)):
            for name in dict.keys(group):
                yield "mesh/%s_arrays/%s" % (location, name), name


def _refuse_unwritable_names(ds: Dataset) -> None:
    """A name HDF5 cannot hold as a link, such as "." or one with a
    "/", is refused even without a check, because the library would
    fail half way through the file rather than write it. A name that
    is only illegal is the validator's (E33)."""
    for where, name in _producer_names(ds):
        if not isinstance(name, str) or name in ("", ".") or "/" in name \
                or "\0" in name:
            raise MestraError(
                "E33", "%r is not a name this file can hold; rename it"
                % (name,), where)


def _refuse_what_the_validator_finds(staged: str, path: str) -> None:
    from .validator import validate

    errors = validate(staged).errors
    if not errors:
        return
    listed = "\n".join("  %s" % f for f in errors[:8])
    if len(errors) > 8:
        listed += "\n  ... and %d more" % (len(errors) - 8)
    raise MestraError(
        errors[0].rule,
        "this dataset breaks %d rule(s), so it was not written; fix "
        "them, or pass check=False to write it anyway:\n%s"
        % (len(errors), listed), path)


def coordinates_attribute(ds: Dataset) -> str:
    """The CF `coordinates` attribute of a row-varying scalar: every
    parameter and row label, in UTF-8 byte order, separated by one
    space (section 11)."""
    names = list(dict.keys(ds.parameters)) + list(dict.keys(ds.labels))
    return " ".join(sorted(names, key=lambda n: n.encode("utf-8")))


# ------------------------------------------------------------------ file

class _Scales:
    """Every dimension scale, by its name on disk, and every dataset
    made, held open until the file closes so that chunks land in
    creation order."""

    def __init__(self) -> None:
        self.root: dict[str, h5py.Dataset] = {}
        self.mesh: dict[str, h5py.Dataset] = {}
        self.keep: list[h5py.Dataset] = []

    def of(self, name: str) -> h5py.Dataset:
        if name in self.mesh:
            return self.mesh[name]
        if name not in self.root:
            raise MestraError(
                "E25", "no dimension scale called %r; the writer should "
                "have made one" % name)
        return self.root[name]


def _write(ds: Dataset, f: h5py.File) -> None:
    _root_attrs(ds, f)
    scales = _make_scales(ds, f)
    _write_categories(ds, f, scales)
    coordinates = coordinates_attribute(ds)
    root: list[tuple[str, Any]] = []
    root += [(n, p) for n, p in dict.items(ds.parameters)]
    root += [(n, lab) for n, lab in dict.items(ds.labels)]
    root += [(n, s) for n, s in dict.items(ds.scalars)]
    for name, item in sorted(root, key=lambda x: x[0].encode("utf-8")):
        if isinstance(item, Parameter):
            _write_parameter(f, name, item, scales)
        elif isinstance(item, Label):
            _write_label(f, name, item, scales)
        else:
            _write_slot(f, name, item, scales,
                        coordinates if item.varies == "row" else "")
    if ds.mesh is not None:
        _write_mesh(ds.mesh, f, scales)
    _write_callables(ds, f)
    if ds.notes or "notes" in ds.present:
        notes = f.create_group("notes")
        for name in sorted(ds.notes, key=lambda n: n.encode("utf-8")):
            _write_note(notes, name, ds.notes[name])
    for name in sorted(ds.opaque):
        opaque.restore(f, name, ds.opaque[name])
    for name in sorted(ds.unknown):
        kind, body = ds.unknown[name]
        opaque.restore_member(f, name, kind, body)
    for dset in scales.keep:
        dset.id.close()
    scales.keep.clear()


def _root_attrs(ds: Dataset, f: h5py.File) -> None:
    write_string_attr(f, "created", ds.created)
    write_string_attr(f, "format", ds.format)
    write_string_attr(f, "writer", ds.writer)
    for name in ("generalisation_group", "title", "license",
                 "references", "source"):
        value = getattr(ds, name)
        if value is not None:
            write_string_attr(f, name, value)
    for name in sorted(ds.extra):
        write_attr(f, name, ds.extra[name])


def _make_scales(ds: Dataset, f: h5py.File) -> _Scales:
    scales = _Scales()
    scales.root["row"] = make_scale(f, "row", ds.row_count, unlimited=True)
    for n in sorted(_component_counts(ds)):
        scales.root["component_%d" % n] = make_scale(
            f, "component_%d" % n, n)
    for name, label in dict.items(ds.labels):
        if label.role == "group":
            table = ds.categories.get(label.category or "")
            scales.root["group_" + name] = make_scale(
                f, "group_" + name, len(table) if table is not None else 0,
                unlimited=True)
    for name in sorted(ds.categories):
        scales.root["category_" + name] = make_scale(
            f, "category_" + name, len(ds.categories[name]),
            unlimited=True)
    return scales


def _component_counts(ds: Dataset) -> set[int]:
    out = set()
    if ds.mesh is not None:
        for slot in ds.mesh.arrays().values():
            if slot.data is not None and len(slot.data.shape) >= 2:
                out.add(int(slot.data.shape[-1]))
    return out


def _attrs(obj: Any, item: Any, order: Sequence[str],
           extra: dict[str, Any] | None = None) -> None:
    for name in order:
        value = getattr(item, name, None)
        if value is None:
            continue
        if name in ("lower", "upper", "level"):
            write_float_attr(obj, name, float(value))
        elif name == "components":
            write_int_attr(obj, name, int(value))
        else:
            write_attr(obj, name, value)
    for name in sorted(extra if extra is not None
                       else getattr(item, "extra", {})):
        write_attr(obj, name, item.extra[name])


# ----------------------------------------------------------- datasets

def _attach(dset: h5py.Dataset, names: Sequence[str],
            scales: _Scales) -> None:
    for axis, name in enumerate(names):
        dset.dims[axis].attach_scale(scales.of(name))


def _disk_dims(dims: Sequence[str], shape: Sequence[int]) -> list[str]:
    return [disk_dimension(d, int(shape[at])) for at, d in enumerate(dims)]


def _growable(group: h5py.Group, name: str, source: Any, dtype: Any,
              keep: list[h5py.Dataset]) -> h5py.Dataset:
    """A dataset whose first axis is `row` or a group: chunked by the
    rule of section 12.3, unlimited along that axis, shuffled and
    compressed with gzip level 1, and filled a block at a time."""
    shape = tuple(int(n) for n in source.shape)
    dtype = np.dtype(dtype)
    chunks = default_chunks(dtype.itemsize, shape)
    dset = group.create_dataset(
        name, shape=shape, dtype=dtype, chunks=chunks,
        maxshape=(None,) + shape[1:], compression="gzip",
        compression_opts=1, shuffle=True, track_times=False)
    keep.append(dset)
    if not shape[0]:
        return dset
    if isinstance(source, MemorySource):
        dset[...] = np.asarray(source.read(), dtype=dtype)
        return dset
    row = max(1, dtype.itemsize * int(np.prod(shape[1:], dtype=np.int64)))
    step = max(chunks[0], (_BLOCK_BYTES // row) // chunks[0] * chunks[0])
    for start in range(0, shape[0], step):
        stop = min(shape[0], start + step)
        dset[start:stop] = np.asarray(source.read(slice(start, stop)),
                                      dtype=dtype)
    return dset


def _strings(group: h5py.Group, name: str, values: Any, *,
             growable: bool, keep: list[h5py.Dataset]) -> h5py.Dataset:
    """A fixed-length UTF-8 string dataset, as wide as its longest
    element (or 1)."""
    flat = [v.decode("utf-8") if isinstance(v, bytes) else str(v)
            for v in np.asarray(values).reshape(-1)]
    raw, size = encode_strings(flat)
    data = raw if raw else None
    kw: dict[str, Any] = {}
    if growable:
        chunks = default_chunks(size, (len(raw),))
        kw = {"chunks": chunks, "maxshape": (None,),
              "compression": "gzip", "compression_opts": 1,
              "shuffle": True}
    else:
        bound = max(1, CHUNK_TARGET // max(1, size))
        kw = {"chunks": (max(1, min(len(raw), bound)),),
              "maxshape": (None,)}
    dset = group.create_dataset(name, shape=(len(raw),),
                                dtype=string_dtype(size), data=data,
                                track_times=False, **kw)
    keep.append(dset)
    return dset


def _write_categories(ds: Dataset, f: h5py.File, scales: _Scales) -> None:
    if not ds.categories and "categories" not in ds.present:
        return
    group = f.create_group("categories")
    for name in sorted(ds.categories):
        dset = _strings(group, name, ds.categories[name].entries,
                        growable=False, keep=scales.keep)
        dset.dims[0].attach_scale(scales.root["category_" + name])


def _write_parameter(f: h5py.File, name: str, item: Parameter,
                     scales: _Scales) -> None:
    source = item.data if item.data is not None else \
        MemorySource(np.zeros(0, "<f8"))
    dset = _growable(f, name, source, source.dtype.newbyteorder("<"),
                     scales.keep)
    _attach(dset, ["row"], scales)
    _attrs(dset, item, _PARAMETER_ORDER)


def _write_label(f: h5py.File, name: str, item: Label,
                 scales: _Scales) -> None:
    source = item.data if item.data is not None else \
        MemorySource(np.zeros(0, "<i4"))
    if source.dtype.kind in "USO":
        dset = _strings(f, name, source.read(), growable=True,
                        keep=scales.keep)
    else:
        dset = _growable(f, name, source, source.dtype.newbyteorder("<"),
                         scales.keep)
    _attach(dset, ["row"], scales)
    _attrs(dset, item, _LABEL_ORDER)


class _Attributes:
    """A slot's attributes as the writer puts them on disk."""

    def __init__(self, slot: Slot, coordinates: str) -> None:
        self.slot = slot
        self.coordinates = coordinates or None
        self.extra = slot.extra

    def __getattr__(self, name: str) -> Any:
        if name == "components":
            return None if self.slot.location == "row" \
                else self.slot.components
        if name == "category":
            return self.slot.category if self.slot.role == "label" \
                else None
        return getattr(self.slot, name)


def _write_slot(group: h5py.Group, name: str, slot: Slot,
                scales: _Scales, coordinates: str = "") -> None:
    attributes = _Attributes(slot, coordinates)
    if slot.data is None:
        holder = group.create_group(name)
        _attrs(holder, attributes, _SLOT_ORDER)
        return
    source = slot.data
    dtype = source.dtype.newbyteorder("<")
    dims = slot.dims
    if dims and (dims[0] == "row" or dims[0].startswith("group:")):
        dset = _growable(group, name, source, dtype, scales.keep)
    else:
        values = np.asarray(source.read(), dtype=dtype)
        dset = group.create_dataset(name, data=values, dtype=dtype,
                                    track_times=False)
        scales.keep.append(dset)
    _attach(dset, _disk_dims(dims, source.shape), scales)
    _attrs(dset, attributes, _SLOT_ORDER)
    if slot.significant_bits is not None:
        write_int_attr(dset, SIGNIFICANT_BITS, int(slot.significant_bits))


def _write_mesh(mesh: Mesh, f: h5py.File, scales: _Scales) -> None:
    group = f.create_group("mesh")
    if mesh.kind is None:
        raise MestraError(
            "E39", "the mesh does not say its kind", "mesh")
    write_string_attr(group, "kind", mesh.kind)
    write_int_attr(group, "n_nodes", mesh.n_nodes)
    write_int_attr(group, "n_cells", mesh.n_cells)
    write_string_attr(group, "support_id", mesh.support_id)
    for name in sorted(mesh.extra):
        write_attr(group, name, mesh.extra[name])
    scales.mesh["node"] = make_scale(group, "node", mesh.n_nodes)
    cells = {which: mesh._cell_array(which) for which, _, _ in _CELLS}
    for which, scale, _ in _CELLS:
        values = cells[which]
        if values is not None:
            scales.mesh[scale] = make_scale(group, scale, len(values))
    for which, scale, dtype in _CELLS:
        values = cells[which]
        if values is None:
            continue
        dset = group.create_dataset(which, data=np.asarray(values,
                                                           dtype=dtype),
                                    dtype=dtype, track_times=False)
        scales.keep.append(dset)
        dset.dims[0].attach_scale(scales.mesh[scale])
    if mesh.coordinates is not None:
        _write_slot(group, "coordinates", mesh.coordinates, scales)
    for which, arrays in (("node_arrays", mesh.node_arrays),
                          ("cell_arrays", mesh.cell_arrays)):
        if not arrays and which not in mesh.present:
            continue
        sub = group.create_group(which)
        for name in arrays:
            _write_slot(sub, name, arrays[name], scales)
    for name in sorted(mesh.opaque):
        opaque.restore(group, name, mesh.opaque[name])


def _write_callables(ds: Dataset, f: h5py.File) -> None:
    if not ds.callables and "callables" not in ds.present:
        return
    group = f.create_group("callables")
    for name in ds.callables:
        obj = ds.callables[name]
        sub = group.create_group(name)
        kind = getattr(obj, "type", "")
        if not kind:
            raise MestraError("E15", "a callable carries a type string",
                              "callables/" + name)
        write_string_attr(sub, "type", kind)
        line = _repr_line(obj)
        if line is not None:
            write_string_attr(sub, "repr", line)
        declared = ds.callable_inputs.get(name)
        if declared is not None:
            write_string_attr(sub, "inputs", " ".join(
                sorted(declared, key=lambda n: n.encode("utf-8"))))
        encode_dict(sub, obj.to_dict())


def _repr_line(obj: Any) -> str | None:
    """The optional one-line description of a callable."""
    if getattr(obj, "_repr_read", False):
        line = getattr(obj, "_repr", None)
        return line if line is None or "\n" not in line else None
    if type(obj).__repr__ is object.__repr__:
        return None
    line = repr(obj)
    return line if "\n" not in line else None


def _write_note(group: h5py.Group, name: str, value: Any) -> None:
    if isinstance(value, np.ndarray):
        group.attrs.create(name, value, dtype=value.dtype)
    else:
        write_attr(group, name, value)


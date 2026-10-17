"""Growing a file by rows, in place.

`append(ds, path, replace_by=None)` writes the rows of `ds`, a dataset
built like a whole file, into the file at `path` without rewriting the
rows it holds. Everything is checked before the file is touched:

- the structure: the same parameters, labels, scalars, mesh and arrays
  with the same attributes (bounds excepted), and the same values
  wherever a slot does not vary by row;
- the appended rows: codes inside their tables (E10), ids unique
  across the file and the new rows (E48), one entry per row (E16).

Then the file grows: category codes are matched by entry name and new
entries extend the tables, new group categories bring their instances
of every array that varies by that group, string datasets that need a
wider width are recreated (leaving their old space unused until the
file is rewritten), bounds widen to cover the new values, and the
dimension scales take their new lengths. With `replace_by` naming an
id label, a row whose id the file already holds is written over that
row. There is no staging: durability is the caller's, who stages a
copy if the file must survive a crash.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import h5py
import numpy as np

from .encoding import (
    encode_strings,
    is_fixed_string,
    leading_bound,
    read_attr,
    scale_name,
    string_dtype,
    string_length,
    write_float_attr,
)
from .errors import MestraError
from .model import Dataset, Parameter, Slot
from .reader import read

__all__ = ["append"]

_COMPARED = ("role", "units", "varies", "components", "source", "output",
             "statistic", "of", "level", "method", "with_respect_to",
             "category", "significant_bits")


def append(ds: Dataset, path: str, replace_by: str | None = None) -> int:
    """Write the rows of `ds` into the file at `path`, in place.

    Returns the number of rows written: those appended and those
    replaced. Refuses, before anything is written, a dataset whose
    structure differs from the file's (rule "" naming the difference)
    or whose rows break E10, E16 or E48.
    """
    with read(str(path)) as old:
        plan = _plan(old, ds, replace_by)
    if plan.written == 0:
        return 0
    with h5py.File(str(path), "r+") as f:
        _apply(f, plan)
    return plan.written


class _Plan:
    """What an append will write, decided before the file is opened
    for writing."""

    def __init__(self) -> None:
        self.n_old = 0
        self.written = 0
        #: Positions in the appended rows of the rows that are new, and
        #: of the rows that replace one, with the file row they replace.
        self.new_rows: np.ndarray = np.zeros(0, np.int64)
        self.replaced: np.ndarray = np.zeros(0, np.int64)
        self.targets: np.ndarray = np.zeros(0, np.int64)
        #: HDF5 path -> values for every appended row, in file dtype.
        self.rows: dict[str, np.ndarray] = {}
        #: table name -> entries to add.
        self.entries: dict[str, list[str]] = {}
        #: group label -> number of new categories.
        self.new_categories: dict[str, int] = {}
        #: HDF5 path of a group-varying array -> instances to add.
        self.instances: dict[str, np.ndarray] = {}
        #: HDF5 path -> (lower, upper) to write.
        self.bounds: dict[str, tuple[Any, Any]] = {}


def _refuse(message: str, where: str = "", rule: str = "") -> MestraError:
    return MestraError(rule, "append refused: %s" % message, where)


def _plan(old: Dataset, ds: Dataset, replace_by: str | None) -> _Plan:
    plan = _Plan()
    plan.n_old = old.row_count
    count = ds.row_count
    _same_names(old, ds)
    if (old.generalisation_group or None) != (ds.generalisation_group
                                              or None):
        raise _refuse("the unit of generalisation differs (%r in the file, "
                      "%r appended)" % (old.generalisation_group,
                                        ds.generalisation_group))
    if sorted(old.callables) != sorted(ds.callables):
        raise _refuse("the callables differ (%s in the file, %s appended)"
                      % (", ".join(old.callables) or "none",
                         ", ".join(ds.callables) or "none"))
    remap = _tables(old, ds, plan)
    # Parameters, with bounds widened to the new values.
    for name, parameter in old.parameters.items():
        mine = ds.parameters[name]
        for key in ("role", "units", "run_group"):
            if getattr(parameter, key) != getattr(mine, key):
                raise _refuse("%s differs: %r in the file, %r appended"
                              % (key, getattr(parameter, key),
                                 getattr(mine, key)),
                              "parameters/" + name)
        values = _cast(mine.values().values, parameter.dtype,
                       "parameters/" + name)
        plan.rows["/" + name] = values
        plan.bounds["/" + name] = _widened(parameter, values)
    # Labels, with codes matched by name and ids checked.
    ids: dict[str, np.ndarray] = {}
    for name, label in old.labels.items():
        mine = ds.labels[name]
        where = "labels/" + name
        if (label.role, label.category) != (mine.role, mine.category):
            raise _refuse("the role or table differs: %s/%s in the file, "
                          "%s/%s appended" % (label.role, label.category,
                                              mine.role, mine.category),
                          where)
        if label.role == "id":
            values = np.asarray(mine.names().values)
            if (values.dtype.kind in "US") != (
                    label.dtype is not None and label.dtype.kind in "USO"):
                raise _refuse("the file's ids and the appended ids are not "
                              "of one kind (text or integers)", where)
            ids[name] = values
            plan.rows["/" + name] = values if values.dtype.kind in "US" \
                else _cast(values, label.dtype, where)
        else:
            codes = _codes(mine.codes().values,
                           ds.categories[mine.category or ""], where)
            plan.rows["/" + name] = _cast(
                remap[label.category or ""][codes] if codes.size else codes,
                label.dtype, where)
    # Which rows are new and which replace a row.
    plan.new_rows = np.arange(count)
    if replace_by is not None:
        label = old.labels.get(replace_by)
        if label is None or label.role != "id":
            raise _refuse("replace_by names %r, which is not an id label of "
                          "the file" % replace_by)
    for name, values in ids.items():
        held = np.asarray(old.labels[name].names().values)
        if np.unique(values).size != values.size:
            raise _refuse("the appended rows repeat an id", "labels/" + name,
                          "E48")
        position = {v: at for at, v in enumerate(held.tolist())}
        found = [position.get(v) for v in values.tolist()]
        hits = [at for at, f in enumerate(found) if f is not None]
        if name == replace_by:
            plan.replaced = np.array(hits, dtype=np.int64)
            plan.targets = np.array([found[at] for at in hits], np.int64)
            plan.new_rows = np.array([at for at, f in enumerate(found)
                                      if f is None], dtype=np.int64)
        elif hits:
            raise _refuse("the file already holds the id %r"
                          % (values[hits[0]].item()
                             if hasattr(values[hits[0]], "item")
                             else values[hits[0]]),
                          "labels/" + name, "E48")
    plan.written = int(plan.new_rows.size + plan.replaced.size)
    # Scalars.
    for name, slot in old.scalars.items():
        mine = ds.scalars[name]
        _same_slot(slot, mine, "scalars/" + name)
        if slot.served:
            continue
        if slot.varies == "none":
            _same_values(slot, mine, "scalars/" + name)
            continue
        plan.rows["/" + name] = _cast(mine.read().values, slot.dtype,
                                      "scalars/" + name)
    # The mesh.
    if (old.mesh is None) != (ds.mesh is None):
        raise _refuse("one of the two has a mesh and the other does not")
    if old.mesh is not None and ds.mesh is not None:
        _mesh(old, ds, plan, remap)
    for where, values in plan.rows.items():
        if len(values) != count:
            raise _refuse("%s holds %d rows and the appended dataset has %d"
                          % (where, len(values), count), where, "E16")
    return plan


def _same_names(old: Dataset, ds: Dataset) -> None:
    for kind in ("parameters", "labels", "scalars"):
        mine, theirs = set(getattr(old, kind)), set(getattr(ds, kind))
        if mine != theirs:
            raise _refuse("the %s differ: %s only in the file, %s only "
                          "appended" % (kind,
                                        ", ".join(sorted(mine - theirs))
                                        or "none",
                                        ", ".join(sorted(theirs - mine))
                                        or "none"))


def _tables(old: Dataset, ds: Dataset, plan: _Plan) -> dict[str, Any]:
    """For each table the appended dataset uses, the file code of each
    appended code, and the entries the file's table gains."""
    remap: dict[str, Any] = {}
    for name, table in ds.categories.items():
        held = old.categories.get(name)
        if held is None:
            raise _refuse("the appended dataset has the category table %r "
                          "and the file does not" % name,
                          "categories/" + name)
        entries = list(held.entries)
        codes = []
        added = []
        for entry in table.entries:
            if entry not in entries:
                entries.append(entry)
                added.append(entry)
            codes.append(entries.index(entry))
        remap[name] = np.array(codes, dtype=np.int64)
        if added:
            plan.entries[name] = added
    for name, label in old.labels.items():
        if label.role == "group" and label.category in plan.entries:
            plan.new_categories[name] = len(plan.entries[label.category])
    return remap


def _same_slot(slot: Slot, mine: Slot, where: str) -> None:
    for key in _COMPARED:
        if key in ("level", "method") and slot.served:
            continue
        a, b = getattr(slot, key), getattr(mine, key)
        if key == "source":
            a, b = slot.served, mine.served
        if a != b:
            raise _refuse("%s differs: %r in the file, %r appended"
                          % (key, a, b), where)


def _same_values(slot: Slot, mine: Slot, where: str) -> None:
    a = np.asarray(slot.read().values)
    b = np.asarray(mine.read().values, dtype=a.dtype)
    if a.shape != b.shape or not np.array_equal(a, b, equal_nan=True):
        raise _refuse("this does not vary by row, and its values differ "
                      "from the file's", where)


def _mesh(old: Dataset, ds: Dataset, plan: _Plan,
          remap: dict[str, Any]) -> None:
    a, b = old.mesh, ds.mesh
    assert a is not None and b is not None
    for key in ("kind", "n_nodes", "n_cells"):
        if getattr(a, key) != getattr(b, key):
            raise _refuse("the mesh's %s differs (%r in the file, %r "
                          "appended)" % (key, getattr(a, key),
                                         getattr(b, key)), "mesh")
    if a.support_id != b.support_id:
        raise _refuse("the mesh's support_id differs: not the same mesh",
                      "mesh")
    slots = [("mesh/coordinates", a.coordinates, b.coordinates)]
    for which, ga, gb in (("node_arrays", a.node_arrays, b.node_arrays),
                          ("cell_arrays", a.cell_arrays, b.cell_arrays)):
        if set(ga) != set(gb):
            raise _refuse("the mesh's %s differ" % which, "mesh/" + which)
        slots += [("mesh/%s/%s" % (which, n), ga[n], gb[n]) for n in ga]
    for where, slot, mine in slots:
        if slot is None or mine is None:
            if slot is not mine:
                raise _refuse("one of the two has coordinates", where)
            continue
        _same_slot(slot, mine, where)
        if slot.served:
            continue
        path = "/" + where
        if slot.varies == "none":
            _same_values(slot, mine, where)
        elif slot.varies == "row":
            values = np.asarray(mine.read().values)
            if slot.role == "label" and slot.category in remap and \
                    values.size:
                values = remap[slot.category][_codes(
                    values, ds.categories[slot.category], where)]
            plan.rows[path] = _cast(values, slot.dtype, where)
        else:
            _instances(old, ds, slot, mine, where, plan)


def _instances(old: Dataset, ds: Dataset, slot: Slot, mine: Slot,
               where: str, plan: _Plan) -> None:
    """A group-varying array: the instances of categories the file has
    must match, and new categories bring theirs."""
    group = slot.varies[len("group:"):]
    table = ds.categories[ds.labels[group].category or ""]
    held = old.categories[old.labels[group].category or ""]
    added = plan.entries.get(old.labels[group].category or "", [])
    values = np.asarray(mine.read().values)
    known = [at for at, e in enumerate(table.entries) if e in held.entries]
    if known:
        theirs = np.asarray(slot.read(
            instances=np.array(sorted(held.entries.index(table.entries[at])
                                      for at in known))).values)
        order = np.argsort([held.entries.index(table.entries[at])
                            for at in known])
        mine_known = values[np.array(known)[order]].astype(theirs.dtype)
        if not np.array_equal(mine_known, theirs, equal_nan=True):
            raise _refuse("an instance of a category the file already has "
                          "differs from the file's", where)
    new = [table.entries.index(e) for e in added]
    plan.instances["/" + where] = _cast(
        values[np.array(new, dtype=np.int64)] if new else
        values[:0], slot.dtype, where)


def _cast(values: Any, dtype: Any, where: str) -> np.ndarray:
    """The appended values in the file's dtype, refused (E20) when that
    would change one."""
    array = np.asarray(values)
    if dtype is None or array.dtype.kind in "US":
        return array
    target = np.dtype(dtype)
    with np.errstate(invalid="ignore", over="ignore"):
        cast = array.astype(target)
    if target.kind in "iu" and array.size and not np.array_equal(
            cast, array):
        raise _refuse("the appended values cannot be held exactly as %s"
                      % target, where, "E20")
    return cast


def _codes(codes: np.ndarray, table: Any, where: str) -> np.ndarray:
    """E10: appended codes inside the appended dataset's own table."""
    codes = np.asarray(codes, dtype=np.int64)
    if codes.size and (codes.min() < 0 or codes.max() >= len(table)):
        raise _refuse("a code is outside its category table", where, "E10")
    return codes


def _widened(parameter: Parameter, values: np.ndarray) -> tuple[Any, Any]:
    lower, upper = parameter.lower, parameter.upper
    finite = values[np.isfinite(values)] if values.dtype.kind == "f" \
        else values
    if finite.size:
        if lower is not None:
            lower = min(float(lower), float(np.min(finite)))
        if upper is not None:
            upper = max(float(upper), float(np.max(finite)))
    return lower, upper


# ------------------------------------------------------------- writing

def _apply(f: h5py.File, plan: _Plan) -> None:
    grown = plan.n_old + int(plan.new_rows.size)
    for name, added in plan.entries.items():
        table = _extend_strings(f, "/categories/" + name, added)
        _resize_scale(f, "/category_" + name, table.shape[0])
    for name, count in plan.new_categories.items():
        scale = f["/group_" + name]
        _resize_scale(f, "/group_" + name, scale.shape[0] + count)
    for path, values in plan.instances.items():
        if values.shape[0]:
            dset = f[path]
            start = dset.shape[0]
            dset.resize(start + values.shape[0], axis=0)
            dset[start:] = values
    for path, values in plan.rows.items():
        _write_rows(f, path, values, plan, grown)
    _resize_scale(f, "/row", grown)
    for path, (lower, upper) in plan.bounds.items():
        dset = f[path]
        if lower is not None:
            write_float_attr(dset, "lower", lower)
        if upper is not None:
            write_float_attr(dset, "upper", upper)


def _resize_scale(f: h5py.File, path: str, length: int) -> None:
    scale = f[path]
    if scale.shape[0] != length:
        scale.resize((length,))
        scale.make_scale(scale_name(length))


def _write_rows(f: h5py.File, path: str, values: np.ndarray, plan: _Plan,
                grown: int) -> None:
    dset = f[path]
    if is_fixed_string(dset.dtype):
        flat = [str(v) for v in values.reshape(-1)]
        _, width = encode_strings(flat)
        if width > (string_length(dset.dtype) or 1):
            dset = _wider(f, path, width)
        size = string_length(dset.dtype) or 1
        values = np.array([v.encode("utf-8").ljust(size, b"\x00")
                           for v in flat], dtype="S%d" % size) \
            if flat else np.zeros(0, "S%d" % size)
        dset = f[path]
    dset.resize(grown, axis=0)
    new = values[plan.new_rows] if plan.new_rows.size else values[:0]
    if new.shape[0]:
        _put(dset, slice(plan.n_old, plan.n_old + new.shape[0]), new)
    if plan.replaced.size:
        order = np.argsort(plan.targets)
        _put(dset, plan.targets[order], values[plan.replaced][order])


def _put(dset: h5py.Dataset, where: Any, values: np.ndarray) -> None:
    if is_fixed_string(dset.dtype):
        raw = [bytes(v) for v in values.reshape(-1)]
        if isinstance(where, slice):
            for at, value in zip(range(where.start, where.stop), raw):
                dset[at] = value
        else:
            for at, value in zip(where, raw):
                dset[int(at)] = value
        return
    dset[where] = values


def _extend_strings(f: h5py.File, path: str,
                    added: Sequence[str]) -> h5py.Dataset:
    dset = f[path]
    _, width = encode_strings(list(added))
    if width > (string_length(dset.dtype) or 1):
        dset = _wider(f, path, width)
    start = dset.shape[0]
    dset.resize(start + len(added), axis=0)
    size = string_length(dset.dtype) or 1
    for at, entry in enumerate(added):
        dset[start + at] = entry.encode("utf-8").ljust(size, b"\x00")
    return dset


def _wider(f: h5py.File, path: str, width: int) -> h5py.Dataset:
    """Recreate a fixed-length string dataset wider, with its values,
    attributes, chunking and dimension scales. HDF5 does not reclaim
    the old space; rewriting the file compacts it."""
    old = f[path]
    values = [bytes(v).rstrip(b"\x00") for v in old[()]]
    attrs = []
    for name in old.attrs:
        if name in ("DIMENSION_LIST", "REFERENCE_LIST", "CLASS", "NAME"):
            continue
        attrs.append((name, read_attr(old, name)))
    scales = [list(dim.values()) for dim in old.dims]
    kw: dict[str, Any] = {"maxshape": old.maxshape}
    if old.chunks is not None:
        # Wider entries hold fewer to a chunk: keep within the default
        # of section 12.3 for the new width, so the grown file draws no
        # W12.
        kw["chunks"] = (min(old.chunks[0], leading_bound(width, ())),) \
            + tuple(old.chunks[1:])
    if old.compression is not None:
        kw["compression"] = old.compression
        kw["compression_opts"] = old.compression_opts
    if old.shuffle:
        kw["shuffle"] = True
    for axis, found in enumerate(scales):
        for scale in found:
            old.dims[axis].detach_scale(scale)
    parent = old.parent
    name = path.rsplit("/", 1)[-1]
    del parent[name]
    raw = [v.ljust(width, b"\x00") for v in values]
    new = parent.create_dataset(name, shape=(len(raw),),
                                dtype=string_dtype(width),
                                data=raw if raw else None,
                                track_times=False, **kw)
    from .encoding import write_attr
    for key, value in attrs:
        write_attr(new, key, value)
    for axis, found in enumerate(scales):
        for scale in found:
            new.dims[axis].attach_scale(scale)
    return new


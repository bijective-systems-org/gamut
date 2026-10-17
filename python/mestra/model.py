"""The objects a version 1 file holds, and the calls that build one.

A `Dataset` is one study or model file: the run table (parameters, row
labels and scalars), at most one mesh with its fields, the category
tables, the callables and the dataset metadata. It is both the builder
and what `read` returns, and it is a handle: copies share one open
file, `close()` releases it, and every array it returns is the
caller's own copy.

    ds = mestra.Dataset(writer="my tool 1")
    ds.add_parameter("mach", [0.4, 0.8], "condition", "1")
    ds.add_label("member", [0, 1], "group", categories=["a", "b"])
    ds.set_generalisation_group("member")
    ds.add_scalar("cl", [0.25, 0.55], "1")
    mesh = ds.set_mesh((types, offsets, conn), coordinates=xyz,
                       units="m", dims=("group:member", "node",
                                        "component"))
    mesh.add_node_array("pressure", p, "Pa", ("row", "node"))

Builders refuse what they can decide at the call, with the rule id.
They do not replace validation of the whole dataset; `write` validates
the file it stages before publishing it.
"""

from __future__ import annotations

import datetime as _datetime
from collections.abc import Iterator, Mapping, Sequence
from typing import Any

import numpy as np

from . import h5safe
from .encoding import decode_string, support_digest
from .errors import Finding, MestraError, TooLarge
from .names import is_legal_name, is_reserved
from .units import is_parseable

__all__ = [
    "FORMAT",
    "NamedArray",
    "CategoryTable",
    "Parameter",
    "Label",
    "Slot",
    "Mesh",
    "Dataset",
    "PARAMETER_ROLES",
    "LABEL_ROLES",
    "TABLE_ROLES",
    "MESH_KINDS",
    "STATISTICS",
    "STATUS_WORDS",
    "RESERVED_ROOT_NAMES",
    "RESERVED_ROOT_PREFIXES",
    "is_reserved_root_name",
]

FORMAT = "mestra/1"

#: Roles of a parameter (spec section 3).
PARAMETER_ROLES = ("design", "condition", "time")
#: Roles of a row label (section 4); the first four carry a table.
LABEL_ROLES = ("group", "categorical", "status", "split", "id")
TABLE_ROLES = ("group", "categorical", "status", "split")
#: At most one label of each of these roles (section 4).
_SINGLE_LABEL_ROLES = ("status", "id")
#: Kinds of the one mesh (section 5.1).
MESH_KINDS = ("mesh", "points")
#: Statistics a relation may carry (section 7).
STATISTICS = ("band", "std")
#: Roles of an array in /mesh (section 11).
MESH_ROLES = ("coordinates", "field", "label")
#: Status words section 4 recommends; only `converged` is fit to use.
STATUS_WORDS = ("converged", "failed", "partial")

#: Names reserved in the root (section 11, E33).
RESERVED_ROOT_NAMES = ("row", "coordinates", "categories", "mesh",
                       "callables", "notes", "private", "VTKHDF")
RESERVED_ROOT_PREFIXES = ("component_", "group_", "category_", "mestra_")

_CALLABLE = "callable:"

#: How many elements `NamedArray` prints rather than summarises.
_REPR_ELEMENTS = 12


def is_reserved_root_name(name: str) -> bool:
    """True for a name a parameter, label or scalar may not take."""
    return name in RESERVED_ROOT_NAMES or any(
        name.startswith(p) for p in RESERVED_ROOT_PREFIXES)


def is_callable_source(source: Any) -> bool:
    """True when `source` is `callable:<id>` with an id after the
    colon. "callable:" alone names no callable and is E36."""
    return (isinstance(source, str) and source.startswith(_CALLABLE)
            and len(source) > len(_CALLABLE))


def _utf8_order(names: Any) -> list[str]:
    return sorted(names, key=lambda n: n.encode("utf-8", "replace"))


# --------------------------------------------------------------- arrays

class NamedArray:
    """A numpy array together with the name of each of its axes.

    `values` is the array, `dims` the logical dimension names (`row`,
    `node`, `cell`, `component`, `group:<k>`) in the same order. Index
    by name with `at()`, or reorder with `transpose()`; a reader in a
    column-major language returns another order, and the names are
    what both agree on.
    """

    __slots__ = ("values", "dims")

    def __init__(self, values: Any, dims: Sequence[str]) -> None:
        self.values = np.asarray(values)
        self.dims = tuple(dims)
        if len(self.dims) != self.values.ndim:
            raise ValueError(
                "%d dimension names for an array of %d axes"
                % (len(self.dims), self.values.ndim))

    def __array__(self, dtype: Any = None, copy: Any = None) -> Any:
        if dtype is None:
            return self.values
        return self.values.astype(dtype, copy=False)

    def __getitem__(self, item: Any) -> Any:
        return self.values[item]

    def __len__(self) -> int:
        return len(self.values)

    def __iter__(self) -> Iterator[Any]:
        return iter(self.values)

    @property
    def shape(self) -> tuple[int, ...]:
        return self.values.shape

    @property
    def dtype(self) -> np.dtype:
        return self.values.dtype

    @property
    def ndim(self) -> int:
        return self.values.ndim

    def axis(self, name: str) -> int:
        """The position of the axis called `name`.

        "instance" names the leading axis of an array that varies
        along a group, whatever the group is called.
        """
        for at, dim in enumerate(self.dims):
            if dim == name:
                return at
            if name == "instance" and dim.startswith("group:"):
                return at
        raise KeyError(
            "no axis called %r; this array has %s"
            % (name, ", ".join(self.dims) or "no axes"))

    def at(self, **where: int) -> Any:
        """The value at the named indices, for example
        `array.at(row=1, node=3, component=0)`. Axes not named come
        back whole."""
        index: list[Any] = [slice(None)] * self.values.ndim
        for name, position in where.items():
            index[self.axis(name)] = position
        return self.values[tuple(index)]

    def transpose(self, *dims: str) -> NamedArray:
        """The same values with the axes in the order named."""
        order = [self.axis(name) for name in dims]
        if len(order) != self.values.ndim:
            raise ValueError("name every axis to transpose")
        return NamedArray(self.values.transpose(order), dims)

    def __repr__(self) -> str:
        if self.values.size <= _REPR_ELEMENTS:
            body = np.array2string(self.values, separator=", ",
                                   threshold=_REPR_ELEMENTS)
        else:
            body = "x".join(str(n) for n in self.values.shape) or "scalar"
        return "NamedArray(%s, dims=%s)" % (body, ", ".join(self.dims))


# ------------------------------------------------------------- selection

def _selector(value: Any, length: int, what: str) -> Any:
    """A slice or a strictly increasing index array, checked.

    Anything else is refused: a negative step, a list out of order or
    with a repeat, an index outside [0, length), a boolean mask. These
    are the forms that read only the chunks holding the selection.
    """
    if value is None:
        return None
    if isinstance(value, slice):
        start, stop, step = value.indices(length)
        if value.step is not None and value.step <= 0:
            raise MestraError(
                "", "%s takes a slice with a positive step, or a strictly "
                "increasing index array" % what)
        return slice(start, max(start, stop), step)
    if isinstance(value, (bool, np.bool_)):
        raise MestraError(
            "", "%s takes a slice or a strictly increasing index array, "
            "not a boolean" % what)
    if isinstance(value, (int, np.integer)):
        raise MestraError(
            "", "%s takes a slice or a strictly increasing index array; "
            "pass [%d] or slice(%d, %d) for one" % (what, value, value,
                                                     value + 1))
    array = np.asarray(value)
    if array.dtype.kind == "b" or (array.size and
                                   array.dtype.kind not in "iu"):
        raise MestraError(
            "", "%s takes a slice or a strictly increasing array of "
            "integer indices, and this is %s" % (what, array.dtype))
    if array.ndim != 1:
        raise MestraError(
            "", "%s takes a one-dimensional index array" % what)
    array = array.astype(np.int64)
    if array.size and (array[0] < 0 or array[-1] >= length):
        raise MestraError(
            "", "%s holds an index outside [0, %d)" % (what, length))
    if array.size > 1 and not bool(np.all(np.diff(array) > 0)):
        raise MestraError(
            "", "%s must be strictly increasing, without repeats; sort "
            "it and remove duplicates first" % what)
    return array


def _count(selection: Any, length: int) -> int:
    if selection is None:
        return length
    if isinstance(selection, slice):
        return len(range(*selection.indices(length)))
    return int(len(selection))


# --------------------------------------------------------------- sources

class _Handle:
    """The one open file a read dataset and its copies share."""

    __slots__ = ("file",)

    def __init__(self, file: Any = None) -> None:
        self.file = file

    def close(self) -> None:
        if self.file is not None:
            try:
                self.file.close()
            finally:
                self.file = None


class _Source:
    """Where an array's values come from: memory, or the file."""

    shape: tuple[int, ...]
    dtype: np.dtype

    def read(self, lead: Any = None, sites: Any = None) -> np.ndarray:
        raise NotImplementedError


class MemorySource(_Source):
    """Values in memory. Reads hand out copies."""

    __slots__ = ("array",)

    def __init__(self, array: Any) -> None:
        self.array = np.asarray(array)

    @property
    def shape(self) -> tuple[int, ...]:   # type: ignore[override]
        return tuple(self.array.shape)

    @property
    def dtype(self) -> np.dtype:          # type: ignore[override]
        return self.array.dtype

    def read(self, lead: Any = None, sites: Any = None) -> np.ndarray:
        selection = _selection(self.array.ndim, lead, sites)
        out = self.array
        for axis, which in enumerate(selection):
            if not (isinstance(which, slice) and which == slice(None)):
                index: list[Any] = [slice(None)] * out.ndim
                index[axis] = which
                out = out[tuple(index)]
        return np.array(out, copy=True)


def _selection(ndim: int, lead: Any, sites: Any) -> list[Any]:
    """One selector per axis: `lead` on the leading axis, `sites` on
    the node or cell axis, which is the second from last."""
    selection: list[Any] = [slice(None)] * ndim
    if lead is not None:
        if ndim == 0:
            raise MestraError("", "a value with no axes takes no rows")
        selection[0] = lead
    if sites is not None:
        if ndim < 2 or (lead is not None and ndim - 2 == 0):
            raise MestraError("", "this array has no node or cell axis")
        selection[ndim - 2] = sites
    return selection


class FileSource(_Source):
    """Values still in the file, read when asked for.

    A read touches the selected part of this one dataset and nothing
    else. Two index arrays (rows and sites together) are read one row
    at a time, so memory stays at the size of the answer.
    """

    __slots__ = ("handle", "path", "_shape", "_dtype", "_decode")

    def __init__(self, handle: _Handle, path: str, shape: Sequence[int],
                 dtype: np.dtype, decode: bool = False) -> None:
        self.handle = handle
        self.path = path
        self._shape = tuple(int(n) for n in shape)
        self._dtype = dtype
        self._decode = decode

    @property
    def shape(self) -> tuple[int, ...]:   # type: ignore[override]
        return self._shape

    @property
    def dtype(self) -> np.dtype:          # type: ignore[override]
        return self._dtype

    def read(self, lead: Any = None, sites: Any = None) -> np.ndarray:
        f = self.handle.file
        if f is None:
            raise MestraError(
                "", "this dataset has been closed; read it again, or "
                "read with lazy=False to keep the values", self.path)
        shape = self._shape
        selection = _selection(len(shape), lead, sites)
        wanted = [_count(which, n) if not (isinstance(which, slice)
                                           and which == slice(None))
                  else n for which, n in zip(selection, shape)]
        count = int(np.prod(wanted)) if wanted else 1
        from . import limits
        if count > limits.MAX_READ_ELEMENTS:
            raise TooLarge(
                "this read would materialise %d elements and the limit "
                "is %d; read fewer rows, nodes or cells at a time"
                % (count, limits.MAX_READ_ELEMENTS), self.path, count)
        lists = [axis for axis, which in enumerate(selection)
                 if isinstance(which, np.ndarray)]
        try:
            dset = f[self.path]
            if 0 in wanted:
                values = np.empty(wanted, dtype=dset.dtype)
            elif not shape:
                values = dset[()]
            elif len(lists) <= 1:
                values = dset[tuple(selection)]
            else:
                # h5py takes one index array per read: read the rows
                # one at a time, each with its sites.
                values = np.empty(wanted, dtype=dset.dtype)
                for at, row in enumerate(selection[0]):
                    values[at] = dset[(int(row),) + tuple(selection[1:])]
        except MestraError:
            raise
        except Exception as exc:
            raise MestraError(
                "E41", "this dataset cannot be read: %s"
                % h5safe._brief(exc), self.path) from None
        values = np.asarray(values)
        if self._decode:
            return _decode_strings(values)
        return values


def _decode_strings(values: Any) -> np.ndarray:
    """Fixed-length bytes as read from HDF5 into text. Leniently: a
    string that is not UTF-8 comes back with the bad bytes replaced,
    and the validator reports it (E26)."""
    array = np.asarray(values)
    flat = [decode_string(v) if isinstance(v, bytes) else str(v)
            for v in array.reshape(-1)]
    return np.array(flat, dtype=np.str_).reshape(array.shape)


# ------------------------------------------------------ category tables

class CategoryTable(Sequence[str]):
    """The named categories of a label. A category code is the
    position of its entry: the first entry is code 0."""

    __slots__ = ("entries", "itemsize")

    def __init__(self, entries: Sequence[str],
                 itemsize: int | None = None) -> None:
        self.entries = [str(e) for e in entries]
        #: The stored byte size, when a file declared a larger one.
        self.itemsize = itemsize

    def __getitem__(self, at: Any) -> Any:
        return self.entries[at]

    def __len__(self) -> int:
        return len(self.entries)

    def code_of(self, name: str) -> int:
        """The code of an entry, by name."""
        try:
            return self.entries.index(name)
        except ValueError:
            raise KeyError(
                "no category %r; this table holds %s"
                % (name, ", ".join(self.entries))) from None

    def __eq__(self, other: object) -> bool:
        if isinstance(other, CategoryTable):
            return self.entries == other.entries
        if isinstance(other, (list, tuple)):
            return self.entries == list(other)
        return NotImplemented

    def __hash__(self) -> int:
        return hash(tuple(self.entries))

    def __repr__(self) -> str:
        return "CategoryTable(%r)" % (self.entries,)


# --------------------------------------------------------- run table

class Parameter:
    """A per-row number that locates the row (section 3): `role`
    (design, condition, time), `units`, optional `lower` and `upper`,
    and on a time parameter an optional `run_group`."""

    def __init__(self, name: str, role: str, *, units: str | None = None,
                 lower: float | None = None, upper: float | None = None,
                 run_group: str | None = None,
                 data: _Source | None = None,
                 extra: Mapping[str, Any] | None = None) -> None:
        self.name = name
        self.role = role
        self.units = units
        self.lower = lower
        self.upper = upper
        self.run_group = run_group
        self.data = data
        #: Attributes this reader does not know, kept for a rewrite.
        self.extra = dict(extra or {})

    @property
    def dtype(self) -> np.dtype | None:
        return self.data.dtype if self.data is not None else None

    def values(self, rows: Any = None) -> NamedArray:
        """The column, or the rows selected (a slice or a strictly
        increasing index array)."""
        if self.data is None:
            return NamedArray(np.zeros(0), ("row",))
        lead = _selector(rows, self.data.shape[0], "rows")
        return NamedArray(self.data.read(lead), ("row",))

    def __repr__(self) -> str:
        return "Parameter(%r, role=%r, units=%r)" % (
            self.name, self.role, self.units)


class Label:
    """A per-row label (section 4): `role` (group, categorical,
    status, split, id) and, except for id, the `category` table its
    codes index."""

    def __init__(self, name: str, role: str, *,
                 category: str | None = None,
                 data: _Source | None = None,
                 extra: Mapping[str, Any] | None = None,
                 dataset: Dataset | None = None) -> None:
        self.name = name
        self.role = role
        self.category = category
        self.data = data
        self.extra = dict(extra or {})
        self._dataset = dataset

    @property
    def dtype(self) -> np.dtype | None:
        return self.data.dtype if self.data is not None else None

    @property
    def table(self) -> CategoryTable | None:
        """The category table, or None for an id label."""
        if self.role == "id" or self._dataset is None:
            return None
        return self._dataset.categories.get(self.category or "")

    def _read(self, rows: Any) -> np.ndarray:
        if self.data is None:
            return np.zeros(0, dtype=np.int64)
        lead = _selector(rows, self.data.shape[0], "rows")
        return self.data.read(lead)

    def codes(self, rows: Any = None) -> NamedArray:
        """The category codes. An id label has no codes; use
        `names()`."""
        if self.role == "id":
            raise MestraError(
                "", "an id label has values and no codes; call names()",
                "labels/" + self.name)
        return NamedArray(self._read(rows), ("row",))

    def names(self, rows: Any = None) -> NamedArray:
        """The values of an id label, and the category names of a
        table-backed label."""
        values = self._read(rows)
        if self.role == "id":
            return NamedArray(values, ("row",))
        table = self.table
        if table is None:
            raise MestraError(
                "E39", "this label names the category table %r, which "
                "the file does not have" % self.category,
                "labels/" + self.name)
        codes = np.asarray(values, dtype=np.int64).reshape(-1)
        bad = np.flatnonzero((codes < 0) | (codes >= len(table)))
        if bad.size:
            raise MestraError(
                "E10", "row %d holds the code %d, outside a table of %d "
                "entries" % (int(bad[0]), int(codes[bad[0]]), len(table)),
                "labels/" + self.name)
        entries = np.array(table.entries if len(table) else [""],
                           dtype=np.str_)
        return NamedArray(entries[codes], ("row",))

    def __repr__(self) -> str:
        return "Label(%r, role=%r)" % (self.name, self.role)


# ---------------------------------------------------------------- slots

class Slot:
    """A scalar, a constant, a field, a region label or the
    coordinates: anything that holds stored data or is served by a
    callable.

    `location` is `row` for a scalar or a constant, `node` or `cell`
    for a mesh array. `varies` is `row`, `none` or `group:<k>`.
    `components` is None for a scalar. `served` is True when a
    callable fills the slot, named by `callable_id` and `output`.
    """

    def __init__(self, name: str, *, location: str, role: str,
                 units: str | None = None, varies: str = "row",
                 components: int | None = None,
                 source: str = "data", output: str | None = None,
                 statistic: str | None = None, of: str | None = None,
                 level: float | None = None, method: str | None = None,
                 with_respect_to: str | None = None,
                 significant_bits: int | None = None,
                 category: str | None = None,
                 coordinates_attr: str | None = None,
                 data: _Source | None = None,
                 dims: Sequence[str] | None = None,
                 extra: Mapping[str, Any] | None = None) -> None:
        self.name = name
        self.location = location
        self.role = role
        self.units = units
        self.varies = varies
        self.components = components
        self.source = source
        self.output = output
        self.statistic = statistic
        self.of = of
        self.level = level
        self.method = method
        self.with_respect_to = with_respect_to
        self.significant_bits = significant_bits
        self.category = category
        #: The CF `coordinates` attribute a file carried, kept so that
        #: a reader can see it; the writer computes its own.
        self.coordinates_attr = coordinates_attr
        self.data = data
        self.extra = dict(extra or {})
        self._dims = tuple(dims) if dims is not None else None
        self._dataset: Dataset | None = None

    @property
    def served(self) -> bool:
        """True when a callable serves this slot rather than data."""
        return is_callable_source(self.source)

    @property
    def callable_id(self) -> str | None:
        """The id of the callable that serves the slot, or None."""
        return self.source[len(_CALLABLE):] if self.served else None

    @property
    def dtype(self) -> np.dtype | None:
        """The stored dtype; None for a served slot."""
        return self.data.dtype if self.data is not None else None

    @property
    def dims(self) -> tuple[str, ...]:
        """The logical name of each stored axis, leading axis first."""
        if self._dims is not None:
            return self._dims
        return _slot_dims(self.varies, self.location)

    @property
    def path(self) -> str:
        """The concept path of the slot."""
        if self.location == "row":
            return "scalars/" + self.name
        if self.role == "coordinates":
            return "mesh/coordinates"
        return "mesh/%s_arrays/%s" % (self.location, self.name)

    def read(self, rows: Any = None, nodes: Any = None,
             cells: Any = None, instances: Any = None) -> NamedArray:
        """The values, or part of them.

        With no selection the array comes back as stored. `rows`
        always means file rows: for a slot that varies by
        `group:<k>` each requested row gets the instance its group
        code selects, and for one that does not vary each requested
        row gets the one instance. `instances` reads a group axis
        directly. `nodes` (on node arrays and coordinates) and
        `cells` (on cell arrays) select along the mesh axis. Each
        selection is a slice or a strictly increasing index array.
        """
        if self.data is None:
            raise MestraError(
                "E30", "this slot is served by %s and holds no data; "
                "evaluate the file first" % self.source, self.path)
        sites = self._sites(nodes, cells)
        if instances is not None:
            if not self.varies.startswith("group:"):
                raise MestraError(
                    "", "instances= reads the group axis of a slot that "
                    "varies by group; this one varies by %s" % self.varies,
                    self.path)
            if rows is not None:
                raise MestraError(
                    "", "pass rows= or instances=, not both", self.path)
            lead = _selector(instances, self.data.shape[0], "instances")
            return NamedArray(self.data.read(lead, sites), self.dims)
        if rows is None:
            return NamedArray(self.data.read(None, sites), self.dims)
        dataset = self._dataset
        row_count = dataset.row_count if dataset is not None else (
            self.data.shape[0] if self.varies == "row" else 0)
        selected = _selector(rows, row_count, "rows")
        row_dims = ("row",) + self.dims[1 if self.varies != "none"
                                        else 0:]
        if self.varies == "row":
            return NamedArray(self.data.read(selected, sites), self.dims)
        wanted = np.arange(row_count)[selected] \
            if isinstance(selected, slice) else selected
        if self.varies == "none":
            one = self.data.read(None, sites)
            return NamedArray(
                np.array(np.broadcast_to(one, (len(wanted),) + one.shape)),
                row_dims)
        group = self.varies[len("group:"):]
        label = dataset.labels.get(group) if dataset is not None else None
        if label is None:
            raise MestraError(
                "E04", "this slot varies by %s and the file has no such "
                "group label" % self.varies, self.path)
        codes = np.asarray(label.codes(wanted).values, dtype=np.int64)
        unique, back = np.unique(codes, return_inverse=True)
        if unique.size and (unique[0] < 0 or
                            unique[-1] >= self.data.shape[0]):
            raise MestraError(
                "E10", "a row's code for %s selects no instance of this "
                "slot" % group, self.path)
        held = self.data.read(unique if unique.size else
                              np.zeros(0, np.int64), sites)
        return NamedArray(np.take(held, back.reshape(-1), axis=0),
                          row_dims)

    def _sites(self, nodes: Any, cells: Any) -> Any:
        if self.location == "row":
            if nodes is not None or cells is not None:
                raise MestraError(
                    "", "a scalar has no node or cell axis", self.path)
            return None
        mine, other = (nodes, cells) if self.location == "node" \
            else (cells, nodes)
        if other is not None:
            raise MestraError(
                "", "this is a %s array; select with %ss=" % (
                    self.location, self.location), self.path)
        if mine is None:
            return None
        assert self.data is not None
        length = self.data.shape[-2] if len(self.data.shape) >= 2 else 0
        return _selector(mine, length, self.location + "s")

    def __repr__(self) -> str:
        return "Slot(%r, location=%r, role=%r, varies=%r, units=%r, " \
               "source=%r)" % (self.name, self.location, self.role,
                               self.varies, self.units, self.source)


def _slot_dims(varies: str, location: str) -> tuple[str, ...]:
    if location == "row":
        return ("row",) if varies == "row" else ()
    dims: list[str] = []
    if varies != "none":
        dims.append(varies)
    dims.append(location)
    dims.append("component")
    return tuple(dims)


# ------------------------------------------------------------- mappings

class _ByName(dict):
    """A mapping of named things that iterates in UTF-8 byte order of
    the names, whatever order they were added in."""

    def __init__(self, what: str) -> None:
        super().__init__()
        self._what = what

    def __iter__(self) -> Iterator[str]:
        return iter(_utf8_order(dict.keys(self)))

    def keys(self) -> Any:
        return list(iter(self))

    def values(self) -> Any:
        return [dict.__getitem__(self, k) for k in self]

    def items(self) -> Any:
        return [(k, dict.__getitem__(self, k)) for k in self]

    def __missing__(self, name: str) -> Any:
        raise KeyError(
            "no %s called %r; this dataset has %s"
            % (self._what, name, ", ".join(self) or "none"))

    def __repr__(self) -> str:
        return "{%s}" % ", ".join("%r: %r" % (k, v) for k, v in
                                  self.items())


class _Notes(dict):
    """`/notes`: free-form public attributes, each a string, an
    int64, a float64 or a one-dimensional numeric array."""

    def __setitem__(self, key: str, value: Any) -> None:
        dict.__setitem__(self, key, _note_value(key, value))

    def update(self, *args: Any, **kw: Any) -> None:
        for key, value in dict(*args, **kw).items():
            self[key] = value


def _note_value(key: Any, value: Any) -> Any:
    if not isinstance(key, str) or not is_legal_name(key) or \
            is_reserved(key):
        raise MestraError(
            "E33", "a note's name is a legal netCDF-4 name that does not "
            "begin with mestra_, and %r is not" % (key,), "notes")
    if isinstance(value, str):
        if "\x00" in value:
            raise MestraError("E26", "a note's text holds a NUL byte",
                              "notes/" + key)
        return value
    if isinstance(value, (bool, np.bool_)):
        raise MestraError(
            "E19", "a note is a string, an int64, a float64 or a "
            "one-dimensional numeric array; pass 0 or 1, or text, for a "
            "flag", "notes/" + key)
    if isinstance(value, (int, np.integer)):
        if not -2**63 <= int(value) < 2**63:
            raise MestraError("E19", "a note's integer must fit in int64",
                              "notes/" + key)
        return int(value)
    if isinstance(value, (float, np.floating)):
        return float(value)
    array = np.asarray(value)
    if array.ndim == 1 and array.dtype.kind in "iu":
        return array.astype("<i8")
    if array.ndim == 1 and array.dtype.kind == "f":
        return array.astype("<f8")
    raise MestraError(
        "E19", "a note is a string, an int64, a float64 or a "
        "one-dimensional numeric array, and this is %s"
        % type(value).__name__, "notes/" + key)


class _Arrays(_ByName):
    """The arrays at one location of the mesh."""

    def __init__(self, location: str) -> None:
        super().__init__("%s array" % location)
        self._location = location

    def __missing__(self, name: str) -> Any:
        if name == "coordinates":
            raise KeyError(
                "the coordinates are mesh.coordinates, not "
                "mesh.%s_arrays['coordinates']" % self._location)
        return super().__missing__(name)


# ----------------------------------------------------------------- mesh

class Mesh:
    """The one mesh of a file (section 5): `kind` (mesh or points),
    `n_nodes`, `n_cells`, `support_id`, `coordinates`, and the
    `node_arrays` and `cell_arrays` on it."""

    def __init__(self, kind: str | None, *, n_nodes: int = 0,
                 n_cells: int = 0, cell_types: Any = None,
                 cell_offsets: Any = None, cell_connectivity: Any = None,
                 stored_support_id: str | None = None,
                 extra: Mapping[str, Any] | None = None) -> None:
        self.kind = kind
        self.n_nodes = int(n_nodes)
        self.n_cells = int(n_cells)
        self._cells: dict[str, _Source | None] = {
            "cell_types": _hold(cell_types, "<u1"),
            "cell_offsets": _hold(cell_offsets, "<i8"),
            "cell_connectivity": _hold(cell_connectivity, "<i8"),
        }
        self.coordinates: Slot | None = None
        self.node_arrays: _Arrays = _Arrays("node")
        self.cell_arrays: _Arrays = _Arrays("cell")
        self.stored_support_id = stored_support_id
        self.extra = dict(extra or {})
        self.dataset: Dataset | None = None
        #: Optional groups the mesh carried, empty ones included.
        self.present: set[str] = set()
        #: Groups under /mesh this reader does not know, kept whole.
        self.opaque: dict[str, Any] = {}

    def cells(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(cell_types, cell_offsets, cell_connectivity), as stored."""
        parts = [self._cells[w] for w in ("cell_types", "cell_offsets",
                                          "cell_connectivity")]
        if any(p is None for p in parts):
            raise MestraError(
                "E38", "a mesh of kind %s carries no cells" % self.kind,
                "mesh")
        return tuple(p.read() for p in parts)  # type: ignore

    def _cell_array(self, which: str) -> np.ndarray | None:
        source = self._cells.get(which)
        return None if source is None else source.read()

    @property
    def support_id(self) -> str:
        """The digest the file stored, or the one computed from the
        arrays for a mesh built in memory."""
        if self.stored_support_id is not None:
            return self.stored_support_id
        return self.computed_support_id()

    def computed_support_id(self) -> str:
        """SHA-256 over the node count and the connectivity and, for
        points, the coordinates widened to float64 (section 5.3)."""
        if self.kind not in MESH_KINDS:
            raise MestraError(
                "E02", "a mesh of kind %r has no support_id" % (self.kind,),
                "mesh")
        if self.kind == "points":
            coords = None
            if self.coordinates is not None and \
                    self.coordinates.data is not None:
                coords = np.asarray(self.coordinates.data.read(),
                                    dtype="<f8")
            return support_digest(self.n_nodes, axis_coordinates=coords)
        return support_digest(self.n_nodes,
                              self._cell_array("cell_types"),
                              self._cell_array("cell_offsets"),
                              self._cell_array("cell_connectivity"))

    def arrays(self) -> dict[str, Slot]:
        """Every array, coordinates included, by its concept path
        below `mesh/`."""
        out: dict[str, Slot] = {}
        if self.coordinates is not None:
            out["coordinates"] = self.coordinates
        for name, slot in self.node_arrays.items():
            out["node_arrays/" + name] = slot
        for name, slot in self.cell_arrays.items():
            out["cell_arrays/" + name] = slot
        return out

    def add_node_array(self, name: str, values: Any, units: str | None,
                       dims: Sequence[str] | None, *,
                       role: str = "field", category: str | None = None,
                       dtype: Any = None, statistic: str | None = None,
                       of: str | None = None, level: float | None = None,
                       method: str | None = None,
                       with_respect_to: str | None = None,
                       round_bits: int | None = None,
                       callable: Any = None, output: str | None = None,
                       components: int | None = None) -> Slot:
        """Add an array over the nodes.

        `dims` names the axes of `values` in your own order: `row` or
        `group:<k>` (or neither, for one value set shared by every
        row), `node`, and `component` (left out, it is added with
        length one). Pass `values` for data, or `callable` and
        `output` for a served slot, which varies by row and takes its
        width from `components` when `dims` names a component axis.
        """
        return self._add("node", name, values, units, dims, role=role,
                         category=category, dtype=dtype,
                         statistic=statistic, of=of, level=level,
                         method=method, with_respect_to=with_respect_to,
                         round_bits=round_bits, callable=callable,
                         output=output, components=components)

    def add_cell_array(self, name: str, values: Any, units: str | None,
                       dims: Sequence[str] | None, *,
                       role: str = "field", category: str | None = None,
                       dtype: Any = None, statistic: str | None = None,
                       of: str | None = None, level: float | None = None,
                       method: str | None = None,
                       with_respect_to: str | None = None,
                       round_bits: int | None = None,
                       callable: Any = None, output: str | None = None,
                       components: int | None = None) -> Slot:
        """Add an array over the cells; as `add_node_array`, with
        `cell` in place of `node`."""
        return self._add("cell", name, values, units, dims, role=role,
                         category=category, dtype=dtype,
                         statistic=statistic, of=of, level=level,
                         method=method, with_respect_to=with_respect_to,
                         round_bits=round_bits, callable=callable,
                         output=output, components=components)

    def _add(self, location: str, name: str, values: Any,
             units: str | None, dims: Sequence[str] | None, *,
             role: str, category: str | None, dtype: Any,
             statistic: str | None, of: str | None,
             level: float | None, method: str | None,
             with_respect_to: str | None, round_bits: int | None,
             callable: Any, output: str | None,
             components: int | None) -> Slot:
        where = "mesh/%s_arrays/%s" % (location, name)
        _check_name(name, where)
        into = self.node_arrays if location == "node" else self.cell_arrays
        if name in dict.keys(into):
            raise MestraError(
                "E33", "the mesh already has a %s array called %r; give "
                "this one another name" % (location, name), where)
        if location == "cell" and self.kind != "mesh":
            raise MestraError(
                "E38", "a points mesh has no cells, so it carries no "
                "cell arrays", where)
        if role == "coordinates":
            raise MestraError(
                "E03", "the mesh has one coordinates array, set by "
                "set_mesh; pass role=\"field\" or \"label\"", where)
        if role not in ("field", "label"):
            raise MestraError(
                "E02", "%r is not a role of a mesh array; pass role= "
                "\"field\" or \"label\"" % (role,), where)
        dataset = self.dataset
        if role == "field":
            _check_units(units, where)
        elif units is not None:
            raise MestraError(
                "E11", "a region label carries no units; pass units=None",
                where)
        if role == "label":
            if statistic or of or with_respect_to or round_bits:
                raise MestraError(
                    "E12", "a region label is not a relation and is not "
                    "rounded", where)
            if callable is not None:
                raise MestraError(
                    "E49", "a region label is stored, not served", where)
        elif category is not None:
            raise MestraError(
                "E39", "category names the table of a region label; a "
                "field has none", where)
        _check_relation(statistic, of, level, method, with_respect_to,
                        served=callable is not None, where=where)
        if with_respect_to == "coordinates" and location != "node":
            raise MestraError(
                "E12", "a derivative with respect to coordinates is a "
                "node array", where)
        if callable is not None:
            if values is not None:
                raise MestraError(
                    "E30", "pass values for data, or callable= for a "
                    "served slot, not both", where)
            _served_storage(dtype, round_bits, where)
            identifier = _callable_id(dataset, callable, where)
            names = tuple(dims) if dims is not None else \
                ("row", location, "component")
            names, varies = _split_dims(names, location, where)
            if varies != "row":
                raise MestraError(
                    "E49", "a served slot varies by row, and dims says %s"
                    % varies, where)
            width = _served_width(names, components, where)
            _check_like_of(into, of, with_respect_to, "row", width, where)
            slot = Slot(name, location=location, role=role, units=units,
                        varies="row", components=width,
                        source=_CALLABLE + identifier,
                        output=output or name, statistic=statistic, of=of,
                        level=level, method=method,
                        with_respect_to=with_respect_to)
            slot._dataset = dataset
            dict.__setitem__(into, name, slot)
            return slot
        if values is None:
            raise MestraError(
                "E30", "a slot holding data needs values; pass values, or "
                "callable= and output= for a served slot", where)
        if dims is None:
            raise MestraError(
                "E04", "name the axes of values with dims, for example "
                "(\"row\", \"%s\", \"component\")" % location, where)
        if role == "label":
            array = _label_codes(values, where)
        else:
            array = _floats(values, dtype, where)
        array, varies, width = _array_from_dims(array, dims, location,
                                                components, where)
        count = self.n_nodes if location == "node" else self.n_cells
        if int(array.shape[-2]) != count:
            raise MestraError(
                "E05", "the %s axis of values is %d long and the mesh has "
                "%d %ss" % (location, int(array.shape[-2]), count,
                            location), where)
        _check_varies(dataset, varies, array, where)
        _check_like_of(into, of, with_respect_to, varies, width, where)
        if role == "label" and category is not None:
            _check_codes(dataset, category, array, where)
        bits = None
        if round_bits is not None:
            array, bits = _round(array, round_bits, where)
        slot = Slot(name, location=location, role=role, units=units,
                    varies=varies, components=width, category=category,
                    statistic=statistic, of=of, level=level, method=method,
                    with_respect_to=with_respect_to,
                    significant_bits=bits, data=MemorySource(array))
        slot._dataset = dataset
        if varies == "row" and dataset is not None:
            dataset._note_rows(int(array.shape[0]), where)
        dict.__setitem__(into, name, slot)
        return slot

    def __repr__(self) -> str:
        return "Mesh(kind=%r, n_nodes=%d, n_cells=%d)" % (
            self.kind, self.n_nodes, self.n_cells)


def _hold(values: Any, dtype: str) -> _Source | None:
    if values is None:
        return None
    if isinstance(values, _Source):
        return values
    return MemorySource(_exact(_numbers(values, None, "mesh"), dtype,
                               "mesh"))


# ------------------------------------------------------------ callables

class Callables(dict):
    """The file's callables by id, each decoded when first asked for.

    An open reads the ids and the `type`, `repr` and `inputs`
    attributes; a dictionary is datasets, and waits until something
    asks for the callable.
    """

    def __init__(self, *args: Any, **kw: Any) -> None:
        super().__init__(*args, **kw)
        self._pending: dict[str, Any] = {}

    def defer(self, name: str, build: Any) -> None:
        self._pending[name] = build
        dict.__setitem__(self, name, None)

    def __getitem__(self, name: Any) -> Any:
        build = self._pending.pop(name, None)
        if build is not None:
            dict.__setitem__(self, name, build())
        return dict.__getitem__(self, name)

    def __setitem__(self, name: Any, value: Any) -> None:
        self._pending.pop(name, None)
        dict.__setitem__(self, name, value)

    def __delitem__(self, name: Any) -> None:
        self._pending.pop(name, None)
        dict.__delitem__(self, name)

    def get(self, name: Any, default: Any = None) -> Any:
        if name not in self:
            return default
        return self[name]      # noqa: SIM401 - self.get would recurse

    def values(self) -> Any:
        self.read_all()
        return dict.values(self)

    def items(self) -> Any:
        self.read_all()
        return dict.items(self)

    def __iter__(self) -> Any:
        return iter(_utf8_order(dict.keys(self)))

    def keys(self) -> Any:
        return list(iter(self))

    def __repr__(self) -> str:
        self.read_all()
        return dict.__repr__(self)

    def read_all(self) -> None:
        """Decode every dictionary still in the file."""
        for name in list(self._pending):
            self[name]


# -------------------------------------------------------------- dataset

class Dataset:
    """One study or model file: its run table, its mesh, its
    callables and its metadata.

    Builders, in the order the interface lists them: `add_parameter`,
    `add_category_table`, `add_label`, `set_generalisation_group`,
    `add_scalar`, `add_constant`, `set_mesh` (then
    `mesh.add_node_array` and `mesh.add_cell_array`), `add_callable`;
    `title`, `license`, `references`, `source` and `notes` are set
    directly.

    It is a handle: a read dataset keeps its file open until
    `close()`, and copies share the file. Arrays it returns are the
    caller's own.
    """

    def __init__(self, writer: str = "mestra python",
                 created: str | None = None) -> None:
        self.format = FORMAT
        self.writer = writer
        self.created = created or _now()
        self.title: str | None = None
        self.license: str | None = None
        self.references: str | None = None
        self.source: str | None = None
        self.generalisation_group: str | None = None
        self.parameters: _ByName = _ByName("parameter")
        self.labels: _ByName = _ByName("label")
        self.scalars: _ByName = _ByName("scalar")
        self.categories: dict[str, CategoryTable] = {}
        self.mesh: Mesh | None = None
        self.callables: Callables = Callables()
        #: The `inputs` each callable declares, by id; None when absent.
        self.callable_inputs: dict[str, frozenset[str] | None] = {}
        self.notes: _Notes = _Notes()
        #: Root attributes this reader does not know (W11), kept.
        self.extra: dict[str, Any] = {}
        #: Groups this reader does not know, and /private, kept whole.
        self.opaque: dict[str, Any] = {}
        #: Root objects with a role this reader does not know (W11),
        #: kept whole for a rewrite.
        self.unknown: dict[str, Any] = {}
        #: Optional groups the file carried, so that an empty one
        #: survives a rewrite.
        self.present: set[str] = set()
        #: What the reader met and could not read: links it does not
        #: follow, members of the wrong kind.
        self.problems: list[Finding] = []
        #: Paths a rewrite could not copy. `write` refuses while any
        #: remain.
        self.lossy: list[str] = []
        self._row_count: int | None = None
        self._handle = _Handle()
        self.path: str | None = None

    # -- structure

    @property
    def row_count(self) -> int:
        """The number of rows."""
        if self._row_count is not None:
            return self._row_count
        for group in (self.parameters, self.labels):
            for item in group.values():
                if item.data is not None:
                    return int(item.data.shape[0])
        for slot in self.scalars.values():
            if slot.data is not None and slot.varies == "row":
                return int(slot.data.shape[0])
        return 0

    def _note_rows(self, count: int, where: str) -> None:
        current = self._row_count
        if current is None:
            current = self.row_count if self._has_rows() else None
        if current is not None and current != count:
            raise MestraError(
                "E16", "values holds %d rows and the dataset has %d; every "
                "parameter, label, scalar and row-varying array has one "
                "entry per row" % (count, current), where)
        self._row_count = count

    def _has_rows(self) -> bool:
        if any(p.data is not None for p in self.parameters.values()):
            return True
        if any(lab.data is not None for lab in self.labels.values()):
            return True
        if any(s.data is not None and s.varies == "row"
               for s in self.scalars.values()):
            return True
        if self.mesh is not None:
            return any(s.data is not None and s.varies == "row"
                       for s in self.mesh.arrays().values())
        return False

    @property
    def kind(self) -> str:
        """`table` (no mesh), `mesh` or `points` (section 9)."""
        if self.mesh is None:
            return "table"
        return self.mesh.kind or "mesh"

    @property
    def addons(self) -> list[str]:
        """The add-ons the content shows, in the order time,
        gradients, uncertainty, model (section 9)."""
        slots = list(self.scalars.values())
        if self.mesh is not None:
            slots += list(self.mesh.arrays().values())
        out = []
        if any(p.role == "time" for p in self.parameters.values()):
            out.append("time")
        if any(s.with_respect_to for s in slots):
            out.append("gradients")
        if any(s.statistic in STATISTICS for s in slots):
            out.append("uncertainty")
        if any(s.served for s in slots):
            out.append("model")
        return out

    def slots(self) -> dict[str, Slot]:
        """Every scalar and mesh array, by concept path."""
        out: dict[str, Slot] = {}
        for name, slot in self.scalars.items():
            out["scalars/" + name] = slot
        if self.mesh is not None:
            for where, slot in self.mesh.arrays().items():
                out["mesh/" + where] = slot
        return out

    def _root_names(self) -> set[str]:
        return (set(dict.keys(self.parameters)) | set(dict.keys(self.labels))
                | set(dict.keys(self.scalars)))

    # -- the run table

    def add_parameter(self, name: str, values: Any, role: str, units: str,
                      lower: float | None = None,
                      upper: float | None = None,
                      run_group: str | None = None) -> Parameter:
        """Add a parameter: a per-row number with a role (design,
        condition, time) and units. `lower` and `upper` declare its
        domain; a bound not given is the observed finite minimum or
        maximum, so a zero-row parameter keeps only what it is given.
        On a time parameter, `run_group` names the group label whose
        categories are the runs."""
        where = "parameters/" + str(name)
        self._check_root_name(name, where)
        if role not in PARAMETER_ROLES:
            raise MestraError(
                "E02", "%r is not a parameter role; pass role= one of %s"
                % (role, ", ".join(PARAMETER_ROLES)), where)
        _check_units(units, where)
        array = _numbers(values, None, where)
        if array.dtype.kind in "iu":
            array = _exact(array, "<i8", where)
        elif array.dtype.kind == "f" or array.size == 0:
            array = array.astype("<f8")
        else:
            raise MestraError(
                "E20", "a parameter is float64 or int64, and these values "
                "are %s" % array.dtype, where)
        if array.ndim != 1:
            raise MestraError(
                "E04", "a parameter has one value per row; these values "
                "have %d axes" % array.ndim, where)
        _check_bounds(lower, upper, where)
        lower, upper = _observed_bounds(array, lower, upper)
        if run_group is not None:
            if role != "time":
                raise MestraError(
                    "", "run_group belongs on a time parameter; this one "
                    "is %s" % role, where)
            label = dict.get(self.labels, run_group)
            if label is not None and label.role != "group":
                raise MestraError(
                    "E47", "run_group names %r, a label of role %s; it "
                    "names a group label" % (run_group, label.role), where)
        parameter = Parameter(
            name, role, units=units,
            lower=None if lower is None else float(lower),
            upper=None if upper is None else float(upper),
            run_group=run_group, data=MemorySource(array))
        self._note_rows(int(array.shape[0]), where)
        dict.__setitem__(self.parameters, name, parameter)
        return parameter

    def add_category_table(self, name: str,
                           entries: Sequence[str]) -> CategoryTable:
        """Add or replace a category table. A label's code is the
        position of its entry, counting from 0."""
        where = "categories/" + str(name)
        _check_name(name, where)
        if isinstance(entries, str):
            raise MestraError(
                "", "entries is a list of names, not one string", where)
        listed = []
        for entry in entries:
            if not isinstance(entry, str):
                raise MestraError(
                    "E20", "a category table holds text, and %r is not"
                    % (entry,), where)
            if "\x00" in entry:
                raise MestraError(
                    "E26", "a category entry holds a NUL byte", where)
            listed.append(entry)
        table = CategoryTable(listed)
        self.categories[name] = table
        return table

    def add_label(self, name: str, values: Any, role: str,
                  category: str | None = None, *,
                  categories: Sequence[str] | None = None) -> Label:
        """Add a row label. A group, categorical, status or split
        label stores integer codes into the category table it names
        with `category`; `categories=[...]` makes that table first,
        named `category` or after the label. An id label stores unique
        integers or strings and has no table."""
        where = "labels/" + str(name)
        self._check_root_name(name, where)
        if role not in LABEL_ROLES:
            raise MestraError(
                "E02", "%r is not a label role; pass role= one of %s"
                % (role, ", ".join(LABEL_ROLES)), where)
        if role in _SINGLE_LABEL_ROLES and any(
                lab.role == role for lab in self.labels.values()):
            raise MestraError(
                "E03", "a file has at most one %s label" % role, where)
        if role == "id":
            if category is not None or categories is not None:
                raise MestraError(
                    "E39", "an id label has no category table", where)
            array = _numbers(values, None, where)
            if array.dtype.kind in "US":
                array = array.astype(np.str_)
                if any("\x00" in v for v in array.reshape(-1)):
                    raise MestraError("E26", "an id holds a NUL byte",
                                      where)
            elif array.dtype.kind in "iu":
                array = _exact(array, "<i8", where)
            elif array.size == 0:
                array = array.astype("<i8")
            else:
                raise MestraError(
                    "E20", "an id label stores int64 or text, and these "
                    "values are %s" % array.dtype, where)
            if array.ndim != 1:
                raise MestraError(
                    "E04", "a label has one value per row", where)
            unique, counts = np.unique(array, return_counts=True)
            if unique.size != array.size:
                raise MestraError(
                    "E48", "the id %r appears %d times; ids are unique"
                    % (unique[counts > 1][0].item(),
                       int(counts[counts > 1][0])), where)
        else:
            if categories is not None:
                category = category or name
                self.add_category_table(category, categories)
            if category is None:
                raise MestraError(
                    "E39", "a %s label names its category table; pass "
                    "category=, or categories=[...]" % role, where)
            if category not in self.categories:
                raise MestraError(
                    "E39", "this dataset has no category table %r; call "
                    "add_category_table first" % category, where)
            array = _label_codes(values, where)
            if array.ndim != 1:
                raise MestraError(
                    "E04", "a label has one value per row", where)
            _check_codes(self, category, array, where)
        label = Label(name, role, category=category if role != "id"
                      else None, data=MemorySource(array), dataset=self)
        self._note_rows(int(array.shape[0]), where)
        dict.__setitem__(self.labels, name, label)
        return label

    def set_generalisation_group(self, name: str | None) -> None:
        """Name the group label a held-out test holds out whole (the
        unit of generalisation). None clears it."""
        if name is None:
            self.generalisation_group = None
            return
        label = dict.get(self.labels, name)
        if label is None or label.role != "group":
            raise MestraError(
                "E47", "the unit of generalisation is a group label, and "
                "%r is %s" % (name, "not a label" if label is None
                              else "a %s label" % label.role),
                "generalisation_group")
        self.generalisation_group = name

    def add_scalar(self, name: str, values: Any, units: str, *,
                   dtype: Any = None, statistic: str | None = None,
                   of: str | None = None, level: float | None = None,
                   method: str | None = None,
                   with_respect_to: str | None = None,
                   round_bits: int | None = None, callable: Any = None,
                   output: str | None = None) -> Slot:
        """Add a result with one value per row. Pass `values` for data,
        or `callable` and `output` for a served slot. A relation names
        its base with `of`: a band (`statistic="band"`, with `level`
        and `method` when stored), a `std`, or a derivative
        (`with_respect_to` naming a parameter)."""
        where = "scalars/" + str(name)
        self._check_root_name(name, where)
        _check_units(units, where)
        _check_relation(statistic, of, level, method, with_respect_to,
                        served=callable is not None, where=where)
        if with_respect_to == "coordinates":
            raise MestraError(
                "E12", "a derivative with respect to coordinates is a "
                "node array whose of names a scalar; add it with "
                "mesh.add_node_array", where)
        _check_like_of(self.scalars, of, with_respect_to, "row", None,
                       where)
        if callable is not None:
            if values is not None:
                raise MestraError(
                    "E30", "pass values for data, or callable= for a "
                    "served slot, not both", where)
            _served_storage(dtype, round_bits, where)
            identifier = _callable_id(self, callable, where)
            slot = Slot(name, location="row", role="scalar", units=units,
                        varies="row", source=_CALLABLE + identifier,
                        output=output or name, statistic=statistic, of=of,
                        level=level, method=method,
                        with_respect_to=with_respect_to)
            slot._dataset = self
            dict.__setitem__(self.scalars, name, slot)
            return slot
        if values is None:
            raise MestraError(
                "E30", "a scalar holding data needs values; pass values, "
                "or callable= and output= for a served slot", where)
        array = _floats(values, dtype, where)
        if array.ndim != 1:
            raise MestraError(
                "E04", "a scalar has one value per row; these values have "
                "%d axes. A constant is add_constant" % array.ndim, where)
        bits = None
        if round_bits is not None:
            array, bits = _round(array, round_bits, where)
        slot = Slot(name, location="row", role="scalar", units=units,
                    varies="row", statistic=statistic, of=of, level=level,
                    method=method, with_respect_to=with_respect_to,
                    significant_bits=bits, data=MemorySource(array))
        slot._dataset = self
        self._note_rows(int(array.shape[0]), where)
        dict.__setitem__(self.scalars, name, slot)
        return slot

    def add_constant(self, name: str, value: Any, units: str, *,
                     dtype: Any = None) -> Slot:
        """Add a constant: one value for every row, with units (a
        reference area, a fixed freestream value)."""
        where = "scalars/" + str(name)
        self._check_root_name(name, where)
        _check_units(units, where)
        array = _floats(value, dtype, where)
        if array.size != 1:
            raise MestraError(
                "E04", "a constant is one value, and this has %d; a "
                "vector is one constant per component" % array.size,
                where)
        array = array.reshape(())
        slot = Slot(name, location="row", role="scalar", units=units,
                    varies="none", data=MemorySource(array))
        slot._dataset = self
        dict.__setitem__(self.scalars, name, slot)
        return slot

    # -- the mesh

    def set_mesh(self, cells: Any = None, *, coordinates: Any = None,
                 units: str, dims: Sequence[str] | None,
                 n_nodes: int | None = None, dtype: Any = None,
                 callable: Any = None, output: str | None = None,
                 components: int | None = None) -> Mesh:
        """Set the one mesh. With `cells` = (types, offsets,
        connectivity) it is a `mesh`; without, `points`, whose
        coordinates are stored and do not vary.

        `dims` names the axes of `coordinates` in your own order:
        `row` or `group:<k>` for coordinates that vary, then `node`
        and `component`. `dtype` is float64 (the default) or float32.
        Coordinates a callable serves (a `mesh` only) take `callable`,
        `output`, `n_nodes` and, when `dims` names a component axis,
        `components`.
        """
        where = "mesh"
        if self.mesh is not None:
            raise MestraError("E03", "a file has at most one mesh", where)
        kind = "mesh" if cells is not None else "points"
        _check_units(units, "mesh/coordinates")
        mesh = Mesh(kind)
        mesh.dataset = self
        if cells is not None:
            try:
                types, offsets, connectivity = cells
            except (TypeError, ValueError):
                raise MestraError(
                    "E38", "cells is (cell_types, cell_offsets, "
                    "cell_connectivity)", where) from None
            mesh._cells = {
                "cell_types": _hold(types, "<u1"),
                "cell_offsets": _hold(offsets, "<i8"),
                "cell_connectivity": _hold(connectivity, "<i8"),
            }
            mesh.n_cells = int(len(np.asarray(types).reshape(-1)))
        if callable is not None:
            if kind != "mesh":
                raise MestraError(
                    "E49", "points coordinates are stored, never served",
                    "mesh/coordinates")
            if coordinates is not None:
                raise MestraError(
                    "E30", "pass coordinates for data, or callable= for "
                    "served coordinates, not both", "mesh/coordinates")
            _served_storage(dtype, None, "mesh/coordinates")
            if n_nodes is None:
                raise MestraError(
                    "E05", "served coordinates store no values, so the "
                    "mesh says its node count; pass n_nodes=", where)
            identifier = _callable_id(self, callable, "mesh/coordinates")
            names = tuple(dims) if dims is not None else \
                ("row", "node", "component")
            names, varies = _split_dims(names, "node", "mesh/coordinates")
            if varies != "row":
                raise MestraError(
                    "E49", "served coordinates vary by row, and dims says "
                    "%s" % varies, "mesh/coordinates")
            width = _served_width(names, components, "mesh/coordinates")
            mesh.n_nodes = int(n_nodes)
            mesh.coordinates = Slot(
                "coordinates", location="node", role="coordinates",
                units=units, varies="row", components=width,
                source=_CALLABLE + identifier,
                output=output or "coordinates")
            mesh.coordinates._dataset = self
            self.mesh = mesh
            return mesh
        if coordinates is None:
            raise MestraError(
                "E03", "the mesh has one coordinates array; pass "
                "coordinates=, or callable= for served ones",
                "mesh/coordinates")
        if dims is None:
            raise MestraError(
                "E04", "name the axes of coordinates with dims, for "
                "example (\"node\", \"component\")", "mesh/coordinates")
        array = _floats(coordinates, dtype, "mesh/coordinates")
        array, varies, width = _array_from_dims(array, dims, "node",
                                                components,
                                                "mesh/coordinates")
        if kind == "points":
            if varies != "none":
                raise MestraError(
                    "E35", "points coordinates do not vary; a probe that "
                    "moves stores its position as a field",
                    "mesh/coordinates")
            if not 1 <= width <= 3:
                raise MestraError(
                    "E03", "points coordinates have one to three "
                    "components, and these have %d" % width,
                    "mesh/coordinates")
        count = int(array.shape[-2])
        if n_nodes is not None and int(n_nodes) != count:
            raise MestraError(
                "E05", "n_nodes says %d and coordinates hold %d nodes"
                % (int(n_nodes), count), "mesh/coordinates")
        mesh.n_nodes = count
        _check_varies(self, varies, array, "mesh/coordinates")
        mesh.coordinates = Slot(
            "coordinates", location="node", role="coordinates",
            units=units, varies=varies, components=width,
            data=MemorySource(array))
        mesh.coordinates._dataset = self
        if varies == "row":
            self._note_rows(int(array.shape[0]), "mesh/coordinates")
        self.mesh = mesh
        return mesh

    # -- callables

    def add_callable(self, id: str, callable: Any,
                     inputs: Any = None) -> Any:
        """Store a callable under an id that slots name with
        `callable=`. `inputs` is the set of names it reads (parameters,
        scalars, and fields as `node_arrays/<name>` or
        `cell_arrays/<name>`); without it the callable is handed every
        design, condition and time parameter."""
        where = "callables/" + str(id)
        _check_name(id, where)
        if not getattr(callable, "type", ""):
            raise MestraError(
                "E15", "a callable carries a type string", where)
        declared = None
        if inputs is None:
            inputs = getattr(callable, "inputs", None)
        if inputs is not None:
            if isinstance(inputs, str):
                raise MestraError(
                    "", "inputs is a collection of names, not one string",
                    where)
            declared = frozenset(str(n) for n in inputs)
            for entry in declared:
                if not entry or " " in entry:
                    raise MestraError(
                        "E45", "an inputs entry is a name without spaces, "
                        "and %r is not" % entry, where)
        self.callables[id] = callable
        self.callable_inputs[id] = declared
        return callable

    # -- adapters

    def to_xarray(self) -> Any:
        """The run table as an xarray Dataset along `row`, with the
        parameters and labels as coordinates and table-backed labels
        decoded to their names; mesh arrays follow under the names
        `coordinates`, `node_arrays/<name>` and `cell_arrays/<name>`.
        Needs xarray, which is not a dependency of this package."""
        import xarray as xr

        from .names import disk_dimension

        variables: dict[str, Any] = {}
        coords: dict[str, Any] = {}
        for name, parameter in self.parameters.items():
            coords[name] = (("row",), parameter.values().values,
                            _attrs_of(parameter))
        for name, label in self.labels.items():
            coords[name] = (("row",), label.names().values,
                            {"role": label.role})
        for name, slot in self.scalars.items():
            if slot.data is None:
                continue
            values = slot.read().values
            variables[name] = (slot.dims, values, _attrs_of(slot))
        if self.mesh is not None:
            for where, slot in self.mesh.arrays().items():
                if slot.data is None:
                    continue
                values = slot.read().values
                dims = tuple(disk_dimension(d, values.shape[at])
                             for at, d in enumerate(slot.dims))
                variables[where] = (dims, values, _attrs_of(slot))
        attrs: dict[str, Any] = {"format": self.format,
                                 "writer": self.writer,
                                 "created": self.created}
        for key in ("title", "license", "references", "source",
                    "generalisation_group"):
            value = getattr(self, key)
            if value is not None:
                attrs[key] = value
        return xr.Dataset(variables, coords=coords, attrs=attrs)

    # -- the file behind a read dataset

    def close(self) -> None:
        """Release the file a read dataset holds. Values already
        returned stay valid; values not yet read cannot be read."""
        self._handle.close()

    def __enter__(self) -> Dataset:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def __repr__(self) -> str:
        return ("Dataset(kind=%s, rows=%d, parameters=%d, labels=%d, "
                "scalars=%d, callables=%d)"
                % (self.kind, self.row_count, len(self.parameters),
                   len(self.labels), len(self.scalars),
                   len(self.callables)))

    def _check_root_name(self, name: Any, where: str) -> None:
        _check_name(name, where)
        if is_reserved_root_name(name):
            raise MestraError(
                "E33", "%r is reserved in the root (row, coordinates, the "
                "group names, and the prefixes component_, group_, "
                "category_ and mestra_); choose another name" % name,
                where)
        if name in self._root_names():
            raise MestraError(
                "E33", "the root already holds %r; parameters, labels and "
                "scalars share one namespace" % name, where)


# ------------------------------------------------------------- helpers

def _attrs_of(obj: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in ("role", "units", "varies", "statistic", "of", "level",
                "method", "with_respect_to", "lower", "upper",
                "run_group", "category"):
        value = getattr(obj, key, None)
        if value is not None:
            out[key] = value
    return out


def _now() -> str:
    """An ISO 8601 timestamp in UTC, to the second."""
    now = _datetime.datetime.now(_datetime.timezone.utc)
    return now.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _check_name(name: Any, where: str) -> None:
    if not isinstance(name, str) or not is_legal_name(name):
        raise MestraError(
            "E33", "%r is not a legal netCDF-4 name: letters, digits, "
            "underscore, hyphen, . and + only, beginning with a letter, a "
            "digit or an underscore" % (name,), where)
    if is_reserved(name):
        raise MestraError(
            "E33", "names beginning with mestra_ are reserved for the "
            "container", where)


def _check_units(units: Any, where: str) -> None:
    if units is None or units == "":
        raise MestraError(
            "E11", "units are required; pass units (\"1\" for a "
            "dimensionless quantity)", where)
    if not isinstance(units, str):
        raise MestraError(
            "E19", "units is a string, and this is %s"
            % type(units).__name__, where)
    if not is_parseable(units):
        raise MestraError(
            "E11", "the units string %r does not parse by the UDUNITS "
            "grammar (for example \"Pa\", \"m s-1\", \"W m-2\", \"1\")"
            % units, where)


def _check_bounds(lower: Any, upper: Any, where: str) -> None:
    for label, value in (("lower", lower), ("upper", upper)):
        if value is None:
            continue
        try:
            finite = bool(np.isfinite(float(value)))
        except (TypeError, ValueError):
            finite = False
        if not finite:
            raise MestraError(
                "E19", "%s is a finite bound, and %r is not"
                % (label, value), where)
    if lower is not None and upper is not None and \
            float(lower) > float(upper):
        raise MestraError(
            "", "lower %r is above upper %r" % (lower, upper), where)


def _observed_bounds(array: np.ndarray, lower: Any, upper: Any
                     ) -> tuple[Any, Any]:
    """The bounds to record: the ones given, and the observed finite
    minimum and maximum for the ones not given."""
    if (lower is not None and upper is not None) or not array.size:
        return lower, upper
    finite = array[np.isfinite(array)] if array.dtype.kind == "f" \
        else array
    if not finite.size:
        return lower, upper
    if lower is None:
        lower = float(np.min(finite))
    if upper is None:
        upper = float(np.max(finite))
    return lower, upper


def _check_relation(statistic: str | None, of: str | None,
                    level: float | None, method: str | None,
                    with_respect_to: str | None, *, served: bool,
                    where: str) -> None:
    """E02 and E12 that the call alone decides (section 7)."""
    if statistic is not None and statistic not in STATISTICS:
        raise MestraError(
            "E02", "%r is not a statistic; a relation is band or std, or "
            "a derivative with with_respect_to" % (statistic,), where)
    if statistic is not None and with_respect_to is not None:
        raise MestraError(
            "E12", "a slot carries statistic or with_respect_to, not both",
            where)
    if statistic != "band" and (level is not None or method is not None):
        raise MestraError(
            "E12", "level and method belong to a band; pass "
            "statistic=\"band\"", where)
    if (statistic is not None or with_respect_to is not None) and not of:
        raise MestraError(
            "E12", "a relation names the result it is about; pass of=",
            where)
    if of is not None and statistic is None and with_respect_to is None:
        raise MestraError(
            "E12", "of names the base of a relation; pass statistic= or "
            "with_respect_to= with it", where)
    if statistic == "std" and served:
        raise MestraError(
            "E12", "a std is stored data about stored data; a callable "
            "serves a band, not a std", where)
    if statistic == "band" and not served:
        if level is None or not 0.0 < float(level) < 1.0:
            raise MestraError(
                "E12", "a band states its coverage as level in (0, 1); "
                "a 1.96-sigma Gaussian band is 0.95", where)
        if not method:
            raise MestraError(
                "E12", "a band says how it was made; pass method= with "
                "one sentence", where)


def _check_like_of(group: dict[str, Any], of: str | None,
                   with_respect_to: str | None, varies: str,
                   components: int | None, where: str) -> None:
    """E12: a relation has the varies and the width of its `of`, which
    is in its own group; a derivative with respect to the coordinates
    is the exception. Decided here when `of` is already there."""
    if of is None or with_respect_to == "coordinates":
        return
    target = dict.get(group, of)
    if target is None:
        return
    if (target.varies, target.components) != (varies, components):
        raise MestraError(
            "E12", "a relation has the shape and varies of its of; %r "
            "varies by %s with %s component(s), and this by %s with %s"
            % (of, target.varies, target.components, varies, components),
            where)


def _callable_id(dataset: Dataset | None, obj: Any, where: str) -> str:
    """The id a callable is stored under, from the id or the object."""
    if isinstance(obj, str):
        identifier = obj
    else:
        identifier = ""
        if dataset is not None:
            for name in dict.keys(dataset.callables):
                if dict.get(dataset.callables, name) is obj:
                    identifier = name
                    break
        if not identifier:
            raise MestraError(
                "E14", "this callable is not in the dataset; call "
                "add_callable(id, callable) first and pass callable=id",
                where)
    if dataset is None or identifier not in dataset.callables:
        raise MestraError(
            "E14", "this dataset holds no callable called %r; call "
            "add_callable first" % identifier, where)
    return identifier


def _numbers(values: Any, dtype: Any, where: str) -> np.ndarray:
    """`values` as one rectangular array, or E20 naming the argument."""
    try:
        return np.asarray(values, dtype=dtype)
    except (ValueError, TypeError) as exc:
        raise MestraError(
            "E20", "values must be a rectangular array of numbers, and "
            "these are not (%s)" % exc, where) from None


def _exact(given: np.ndarray, dtype: Any, where: str) -> np.ndarray:
    """`given` stored as `dtype`, or E20 when that changes a value."""
    if given.size == 0:
        return given.astype(dtype)
    if given.dtype.kind not in "biuf":
        raise MestraError(
            "E20", "values must be integers, and these are %s"
            % given.dtype, where)
    if np.can_cast(given.dtype, dtype):
        # A copy, always: the dataset owns its values, so changing the
        # caller's array afterwards does not change the dataset.
        return given.astype(dtype)
    with np.errstate(invalid="ignore"):
        array = given.astype(dtype)
    changed = np.flatnonzero(array != given)
    if not changed.size:
        return array
    first = given.reshape(-1)[changed[0]]
    raise MestraError(
        "E20", "values holds %s, which %s cannot hold exactly"
        % (first, np.dtype(dtype)), where)


def _floats(values: Any, dtype: Any, where: str) -> np.ndarray:
    """A float result as float32 or float64 (float64 by default)."""
    want = np.dtype("<f8") if dtype is None else np.dtype(dtype)
    if want not in (np.dtype("<f4"), np.dtype("<f8")):
        raise MestraError(
            "E20", "a scalar, field or coordinates is float32 or float64, "
            "and dtype says %s" % want, where)
    given = _numbers(values, None, where)
    if given.dtype.kind not in "biuf" and given.size:
        raise MestraError(
            "E20", "values must be numbers, and these are %s"
            % given.dtype, where)
    if given.dtype.kind == "b":
        raise MestraError(
            "E20", "values must be numbers, not booleans", where)
    return given.astype(want)


def _label_codes(values: Any, where: str) -> np.ndarray:
    """Integer codes as int32, or int64 when they do not fit."""
    given = _numbers(values, None, where)
    if given.size == 0:
        return given.astype("<i4")
    if given.dtype.kind not in "iu":
        raise MestraError(
            "E20", "a label stores integer codes, and these values are "
            "%s; pass the codes, and their names as a category table"
            % given.dtype, where)
    if given.min() >= -2**31 and given.max() < 2**31:
        return given.astype("<i4")
    return _exact(given, "<i8", where)


def _check_codes(dataset: Dataset | None, category: str,
                 array: np.ndarray, where: str) -> None:
    table = None if dataset is None else dataset.categories.get(category)
    if table is None:
        raise MestraError(
            "E39", "this dataset has no category table %r; call "
            "add_category_table first" % category, where)
    if array.size and ((array < 0) | (array >= len(table))).any():
        raise MestraError(
            "E10", "a code is outside the category table %r of %d "
            "entries; a code is an entry's position, counting from 0"
            % (category, len(table)), where)


def _check_varies(dataset: Dataset | None, varies: str,
                  array: np.ndarray | None, where: str) -> None:
    """E04 and E34: a group-varying array against its group label."""
    if not varies.startswith("group:"):
        return
    group = varies[len("group:"):]
    label = None if dataset is None else dict.get(dataset.labels, group)
    if label is None or label.role != "group":
        raise MestraError(
            "E04", "varies is %s and the dataset has no group label %r; "
            "add the label before the arrays that vary along it"
            % (varies, group), where)
    table = dataset.categories.get(label.category or "") \
        if dataset is not None else None
    if array is not None and table is not None and \
            int(array.shape[0]) != len(table):
        raise MestraError(
            "E34", "values holds %d instances and the group %r has %d "
            "categories; a group-varying array holds one per category"
            % (int(array.shape[0]), group, len(table)), where)


def _split_dims(dims: Sequence[str], location: str,
                where: str) -> tuple[tuple[str, ...], str]:
    """The caller's axis names, checked, and the `varies` they mean."""
    if isinstance(dims, str):
        raise MestraError(
            "E04", "dims is a sequence of axis names, such as (\"row\", "
            "\"%s\")" % location, where)
    names = tuple(str(d) for d in dims)
    if len(set(names)) != len(names):
        raise MestraError(
            "E04", "dims names an axis twice (%s)" % ", ".join(names),
            where)
    other = "cell" if location == "node" else "node"
    for one in names:
        if one in ("row", location, "component") or \
                one.startswith("group:"):
            continue
        if one == other:
            raise MestraError(
                "E04", "dims names a %s axis on an array over the %ss"
                % (other, location), where)
        raise MestraError(
            "E04", "dims may name row or group:<k>, %s and component, and "
            "this names %r" % (location, one), where)
    leading = [n for n in names if n == "row" or n.startswith("group:")]
    if len(leading) > 1:
        raise MestraError(
            "E04", "dims names %d leading axes (%s); an array varies along "
            "one of them or none" % (len(leading), ", ".join(leading)),
            where)
    if location not in names:
        raise MestraError(
            "E04", "dims names no %s axis" % location, where)
    return names, (leading[0] if leading else "none")


def _served_storage(dtype: Any, round_bits: Any, where: str) -> None:
    """A served slot stores nothing, so it takes no dtype and no
    rounding; evaluation writes its values as float64."""
    if dtype is not None or round_bits is not None:
        raise MestraError(
            "", "a served slot holds no data, so dtype and round_bits do "
            "not apply; evaluation writes its values as float64", where)


def _served_width(names: Sequence[str], components: int | None,
                  where: str) -> int:
    if "component" not in names:
        if components not in (None, 1):
            raise MestraError(
                "E31", "dims names no component axis, so the slot has one "
                "component, and components says %r" % (components,), where)
        return 1
    if components is None or int(components) < 1:
        raise MestraError(
            "E31", "a served slot stores no values, so with a component "
            "axis in dims it says its width; pass components=", where)
    return int(components)


def _array_from_dims(array: np.ndarray, dims: Sequence[str],
                     location: str, components: int | None,
                     where: str) -> tuple[np.ndarray, str, int]:
    """The array in stored order, (lead?, site, component), from the
    order the caller has it in."""
    names, varies = _split_dims(dims, location, where)
    if len(names) != array.ndim:
        raise MestraError(
            "E04", "dims names %d axes and values has %d; name every axis"
            % (len(names), array.ndim), where)
    wanted = _slot_dims(varies, location)
    order = [names.index(d) for d in wanted if d in names]
    array = array.transpose(order)
    if "component" not in names:
        array = array.reshape(array.shape + (1,))
    width = int(array.shape[-1])
    if components is not None and int(components) != width:
        raise MestraError(
            "E31", "components says %d and the component axis is %d long"
            % (int(components), width), where)
    if width < 1:
        raise MestraError("E31", "the component axis is empty", where)
    return np.ascontiguousarray(array), varies, width


def _round(array: np.ndarray, bits: Any, where: str
           ) -> tuple[np.ndarray, int]:
    """Keep `bits` explicit mantissa bits, round half to even, NaN and
    the infinities unchanged (section 12.2). A finite value that would
    round to infinity is truncated instead, so the bound holds."""
    if isinstance(bits, (bool, np.bool_)) or \
            not isinstance(bits, (int, np.integer)):
        raise MestraError("", "round_bits is an integer", where)
    uint: Any
    if array.dtype == np.dtype("<f4"):
        width, uint = 23, np.uint32
    elif array.dtype == np.dtype("<f8"):
        width, uint = 52, np.uint64
    else:
        raise MestraError(
            "", "round_bits applies to float32 and float64 values", where)
    n = int(bits)
    if not 1 <= n <= width:
        raise MestraError(
            "", "round_bits keeps 1 to %d explicit mantissa bits for %s, "
            "and this is %d" % (width, array.dtype, n), where)
    drop = width - n
    if drop == 0:
        return array.copy(), n
    raw = np.ascontiguousarray(array).view(uint)
    one = uint(1)
    half = uint(1) << uint(drop - 1)
    mask = ~((one << uint(drop)) - one)
    odd = (raw >> uint(drop)) & one
    with np.errstate(over="ignore"):
        rounded = ((raw + (half - one) + odd) & mask).astype(uint)
    truncated = raw & mask
    out = rounded.view(array.dtype).copy()
    finite = np.isfinite(array)
    overflow = finite & ~np.isfinite(out)
    if overflow.any():
        out[overflow] = truncated.view(array.dtype)[overflow]
    out[~finite] = array[~finite]
    return out, n

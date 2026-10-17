"""The callable protocol, its registry, and the `affine` reference.

A callable is called with an input table and returns one `Prediction`
per output it serves; `to_dict` represents it as a nested dictionary
and `from_dict`, dispatched on its public `type`, is the inverse;
`repr` is an optional one-line description. `inputs` is the set of
names the file declares it reads, or None. Everything else it knows
is inside its dictionary and is its own business.

The input table maps each input name to a `NamedArray` whose leading
axis is `row`: `(row)` for a parameter or a scalar, `(row, node,
component)` or `(row, cell, component)` for a field, all with one row
count, `row_count`. A version 0 callable that reads one-dimensional
parameter columns reads this table unchanged.

    class Lookup(mestra.Callable):
        type = "lookup"
        def __call__(self, table): ...
        def to_dict(self): ...
        @classmethod
        def from_dict(cls, d): ...

    mestra.register_callable(Lookup)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar

import numpy as np

from .errors import MestraError
from .model import NamedArray

__all__ = [
    "Prediction",
    "Callable",
    "Affine",
    "OpaqueCallable",
    "InputTable",
    "register_callable",
    "callable_types",
    "callable_from_dict",
    "input_table",
]


# ----------------------------------------------------- the input table

class InputTable(Mapping[str, NamedArray]):
    """What a callable is called with: input name to a `NamedArray`
    whose leading axis is `row`, all of `row_count` rows."""

    def __init__(self, columns: Mapping[str, NamedArray],
                 row_count: int) -> None:
        self._columns = dict(columns)
        self.row_count = int(row_count)

    def __getitem__(self, name: str) -> NamedArray:
        try:
            return self._columns[name]
        except KeyError:
            raise KeyError(
                "the input table has no column %r; it has %s"
                % (name, ", ".join(self._columns) or "none")) from None

    def __iter__(self) -> Iterator[str]:
        return iter(self._columns)

    def __len__(self) -> int:
        return len(self._columns)

    def __repr__(self) -> str:
        return "InputTable(%d rows: %s)" % (
            self.row_count, ", ".join(self._columns))


def input_table(source: Any, names: Sequence[str] | None = None
                ) -> InputTable:
    """The table a callable receives.

    From a `Dataset`: the columns `names` lists, each a parameter, a
    scalar, or a field as `node_arrays/<name>` or `cell_arrays/<name>`
    (read for every row), or by default every design, condition and
    time parameter in UTF-8 byte order of their names. From a mapping:
    each value as a `NamedArray` with a leading `row` axis, a plain
    one-dimensional array being a column, and with `names` the
    columns it keeps. A two-dimensional array of shape (rows, columns)
    with `names` in column order is also a table.
    """
    from .model import Dataset

    if isinstance(source, InputTable) and names is None:
        return source
    if isinstance(source, Dataset):
        return _from_dataset(source, names)
    if isinstance(source, Mapping):
        wanted = list(source) if names is None else list(names)
        columns: dict[str, NamedArray] = {}
        for name in wanted:
            if name not in source:
                raise MestraError(
                    "", "the table has no column %r" % (name,))
            columns[str(name)] = _column(str(name), source[name])
        return _checked(columns)
    values = np.asarray(source)
    if values.ndim != 2 or names is None or len(names) != values.shape[1]:
        raise MestraError(
            "", "an input table is a mapping of name to column, a "
            "Dataset, or a two-dimensional array with one name per "
            "column in names=")
    return _checked({str(n): NamedArray(values[:, at], ("row",))
                     for at, n in enumerate(names)})


def _column(name: str, values: Any) -> NamedArray:
    if isinstance(values, NamedArray):
        if not values.dims or values.dims[0] != "row":
            raise MestraError(
                "", "every column of an input table has a leading row "
                "axis, and %s has %s" % (name, ", ".join(values.dims)))
        return values
    array = np.asarray(values)
    if array.ndim == 0:
        array = array.reshape(1)
    if array.ndim == 1:
        return NamedArray(array, ("row",))
    if array.ndim == 3:
        site = "cell" if name.startswith("cell_arrays/") else "node"
        return NamedArray(array, ("row", site, "component"))
    raise MestraError(
        "", "a column of an input table is (row) or (row, node | cell, "
        "component), and %s has %d axes" % (name, array.ndim))


def _checked(columns: dict[str, NamedArray]) -> InputTable:
    lengths = {len(c.values) for c in columns.values()}
    if len(lengths) > 1:
        raise MestraError(
            "", "every column of an input table has the same row count; "
            "these have %s" % ", ".join(str(n) for n in sorted(lengths)))
    return InputTable(columns, lengths.pop() if lengths else 0)


def _from_dataset(ds: Any, names: Sequence[str] | None) -> InputTable:
    if names is None:
        names = [n for n, p in ds.parameters.items()
                 if p.role in ("design", "condition", "time")]
    rows = slice(0, ds.row_count)
    columns: dict[str, NamedArray] = {}
    for name in names:
        if name in ds.parameters:
            columns[name] = ds.parameters[name].values()
        elif name in ds.scalars:
            slot = ds.scalars[name]
            columns[name] = slot.read(rows=rows)
        elif name.startswith(("node_arrays/", "cell_arrays/")) and \
                ds.mesh is not None:
            location, short = name.split("/", 1)
            group = ds.mesh.node_arrays if location == "node_arrays" \
                else ds.mesh.cell_arrays
            if short not in group:
                raise MestraError("E45", "the mesh has no %s" % name)
            columns[name] = group[short].read(rows=rows)
        else:
            raise MestraError(
                "E45", "%r names no parameter, scalar or field of this "
                "dataset" % name)
    return InputTable(columns, ds.row_count)


# -------------------------------------------------------- the record

@dataclass(frozen=True)
class Prediction:
    """What a callable returns for one output.

    `mean` is shaped as the slot is stored: (row, node | cell,
    component) for a field, (row) for a scalar. `uncertainty` is
    optional: a band, the half-width of the interval around `mean` at
    coverage `level`, made as `method` says. A band missing its level
    or its method, of another shape, or negative is refused here.
    """

    mean: np.ndarray
    uncertainty: np.ndarray | None = None
    level: float | None = None
    method: str | None = None

    def __post_init__(self) -> None:
        mean = np.asarray(self.mean, dtype="<f8")
        object.__setattr__(self, "mean", mean)
        if self.uncertainty is None:
            if self.level is not None or self.method is not None:
                raise MestraError(
                    "", "level and method go with an uncertainty; a "
                    "prediction without one has neither")
            return
        band = np.asarray(self.uncertainty, dtype="<f8")
        if band.shape != mean.shape:
            raise MestraError(
                "", "a band has the shape of its mean; the mean is %s and "
                "the band %s" % (mean.shape, band.shape))
        if self.level is None or not 0.0 < float(self.level) < 1.0:
            raise MestraError(
                "", "a band states its coverage as level in (0, 1), and "
                "this one gives %r" % (self.level,))
        if not self.method:
            raise MestraError(
                "", "a band says how it was made; give method one "
                "sentence")
        if bool((band < 0).any()):
            raise MestraError(
                "", "a band is a half-width and is never negative")
        object.__setattr__(self, "uncertainty", band)
        object.__setattr__(self, "level", float(self.level))
        object.__setattr__(self, "method", str(self.method))

    @property
    def has_uncertainty(self) -> bool:
        """True when the record carries a band."""
        return self.uncertainty is not None


# ---------------------------------------------------------- the protocol

class Callable(ABC):
    """An input table in, predictions out, plus a dictionary that
    represents it. A subclass sets `type` and implements the three
    methods below. `inputs` is what the file declares it reads."""

    type: ClassVar[str] = ""
    inputs: frozenset[str] | None = None

    @abstractmethod
    def __call__(self, table: Any) -> dict[str, Prediction]:
        """One `Prediction` per output, from an input table."""

    @abstractmethod
    def to_dict(self) -> dict[str, Any]:
        """A nested dictionary of arrays, numbers and strings that
        fully represents this callable."""

    @classmethod
    @abstractmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Callable:
        """Rebuild a callable from the dictionary `to_dict` made."""


_REGISTRY: dict[str, Any] = {}


def register_callable(kind: Any) -> Any:
    """Register a callable class under its `type` string. Usable as a
    decorator; a second registration of a type replaces the first."""
    if not getattr(kind, "type", ""):
        raise MestraError("E15", "a callable class sets a type string",
                          getattr(kind, "__name__", ""))
    _REGISTRY[kind.type] = kind
    return kind


def callable_types() -> dict[str, Any]:
    """The registered callable types, by type string."""
    return dict(_REGISTRY)


def callable_from_dict(kind: str, d: Mapping[str, Any],
                       repr_line: str | None = None,
                       inputs: frozenset[str] | None = None) -> Any:
    """Rebuild a callable of type `kind`, or keep it opaque when the
    type is not registered."""
    known = _REGISTRY.get(kind)
    if known is None:
        return OpaqueCallable(kind, d, repr_line, inputs)
    made = known.from_dict(d)
    try:
        made._repr = repr_line
        made._repr_read = True
        made.inputs = inputs
    except AttributeError:                              # pragma: no cover
        pass
    return made


class OpaqueCallable:
    """A callable whose type this reader does not own: its `type`,
    `inputs`, `repr` line and dictionary, copied unchanged on write
    and refused on evaluation."""

    def __init__(self, kind: str, d: Mapping[str, Any],
                 repr_line: str | None = None,
                 inputs: frozenset[str] | None = None) -> None:
        self.type = kind
        self._dict = dict(d)
        self._repr = repr_line
        self._repr_read = True
        self.inputs = inputs

    def __call__(self, table: Any) -> dict[str, Prediction]:
        raise MestraError(
            "", "this reader does not own the callable type %r, so it can "
            "copy it but not evaluate it. Import the package that "
            "provides the type, which registers it, or register a class "
            "with mestra.register_callable" % self.type)

    def to_dict(self) -> dict[str, Any]:
        """The dictionary as it was read, unchanged."""
        return dict(self._dict)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> OpaqueCallable:
        return cls("", d)

    def __repr__(self) -> str:
        return self._repr or "OpaqueCallable(type=%r)" % self.type


# ------------------------------------------------------------- affine

_AFFINE_KEYS = frozenset(["A", "b", "shape"])
_BAND_KEYS = frozenset(["uncertainty", "level", "method"])


@register_callable
class Affine(Callable):
    """y = A x + b per output: the one callable type this package
    defines, so that the protocol, the codec and evaluation can be
    tested with no proprietary model. x is the vector of the declared
    `keys`, taken from the input table in that order; an output may
    carry a constant band.

        m = Affine(["mach", "alpha"],
                   {"cl": {"A": [[2.0, 0.1]], "b": [0.05],
                           "shape": []}})
        m({"mach": [0.5], "alpha": [4.0]})["cl"].mean
    """

    type: ClassVar[str] = "affine"

    def __init__(self, keys: Sequence[str],
                 outputs: Mapping[str, Mapping[str, Any]],
                 repr_line: str | None = None) -> None:
        self.keys = [str(k) for k in keys]
        self.inputs = None
        self.outputs: dict[str, dict[str, Any]] = {}
        for name, entry in outputs.items():
            self.outputs[str(name)] = _affine_entry(str(name), entry,
                                                    len(self.keys))
        self._repr = repr_line

    def __call__(self, table: Any) -> dict[str, Prediction]:
        """Evaluate every output on an input table."""
        given = input_table(table)
        missing = [k for k in self.keys if k not in given]
        if missing:
            raise MestraError(
                "", "the input table has no column %s; this callable "
                "reads %s" % (", ".join(missing), ", ".join(self.keys)))
        rows = given.row_count
        columns = np.empty((rows, len(self.keys)), dtype="<f8")
        for at, name in enumerate(self.keys):
            column = np.asarray(given[name].values, dtype="<f8")
            if column.ndim != 1:
                raise MestraError(
                    "", "affine reads one value per row, and %s has %d "
                    "axes" % (name, column.ndim))
            columns[:, at] = column
        return {name: self._predict(entry, columns)
                for name, entry in self.outputs.items()}

    def to_dict(self) -> dict[str, Any]:
        """keys and outputs, and nothing else."""
        keys: Any = (list(self.keys) if self.keys
                     else np.zeros(0, dtype=np.str_))
        return {
            "keys": keys,
            "outputs": {name: {key: entry[key]
                               for key in ("A", "b", "shape",
                                           "uncertainty", "level",
                                           "method") if key in entry}
                        for name, entry in self.outputs.items()},
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Affine:
        if set(d) != {"keys", "outputs"}:
            raise MestraError(
                "", "an affine dictionary holds keys and outputs and "
                "nothing else; this one holds %s" % ", ".join(sorted(d)))
        return cls([str(k) for k in d["keys"]], d["outputs"])

    def __repr__(self) -> str:
        if self._repr:
            return self._repr
        return "affine(%s -> %s)" % (", ".join(self.keys),
                                     ", ".join(sorted(self.outputs)))

    @classmethod
    def _predict(cls, entry: Mapping[str, Any],
                 columns: np.ndarray) -> Prediction:
        mean = cls._evaluate(entry, columns)
        if "uncertainty" not in entry:
            return Prediction(mean)
        band = np.asarray(entry["uncertainty"]).reshape(mean.shape[1:])
        return Prediction(mean, np.broadcast_to(band, mean.shape).copy(),
                          level=entry["level"], method=entry["method"])

    @staticmethod
    def _evaluate(entry: Mapping[str, Any],
                  columns: np.ndarray) -> np.ndarray:
        """Y = X A' + b, accumulated over the keys in their declared
        order with b added last and no fused multiply-add."""
        matrix = entry["A"]
        rows = columns.shape[0]
        out = np.zeros((rows, matrix.shape[0]), dtype="<f8")
        for at in range(matrix.shape[1]):
            out += columns[:, at:at + 1] * matrix[:, at]
        out += entry["b"]
        shape = tuple(int(n) for n in entry["shape"])
        return out.reshape((rows,) + shape)


def _affine_entry(name: str, entry: Mapping[str, Any],
                  n_keys: int) -> dict[str, Any]:
    extra = set(entry) - _AFFINE_KEYS - _BAND_KEYS
    if extra:
        raise MestraError(
            "", "an affine output holds A, b and shape, and a band as "
            "uncertainty, level and method; this one also holds %s"
            % ", ".join(sorted(extra)), name)
    missing = _AFFINE_KEYS - set(entry)
    if missing:
        raise MestraError(
            "", "an affine output holds A, b and shape; this one has no "
            "%s" % ", ".join(sorted(missing)), name)
    band_keys = set(entry) & _BAND_KEYS
    if band_keys and band_keys != _BAND_KEYS:
        raise MestraError(
            "", "a band on an affine output is all three of uncertainty, "
            "level and method", name)
    shape = np.asarray(entry["shape"], dtype="<i8").reshape(-1)
    matrix = np.asarray(entry["A"], dtype="<f8")
    offset = np.asarray(entry["b"], dtype="<f8").reshape(-1)
    flat = int(np.prod(shape)) if shape.size else 1
    if matrix.shape != (flat, n_keys):
        raise MestraError(
            "", "A is (%d, %d) for this output and holds %s"
            % (flat, n_keys, matrix.shape), name)
    if offset.shape != (flat,):
        raise MestraError(
            "", "b is (%d,) for this output and holds %s"
            % (flat, offset.shape), name)
    made: dict[str, Any] = {"A": matrix, "b": offset, "shape": shape}
    if band_keys:
        band = np.asarray(entry["uncertainty"], dtype="<f8").reshape(-1)
        if band.shape != (flat,):
            raise MestraError(
                "", "uncertainty is (%d,) for this output" % flat, name)
        level = float(entry["level"])
        if not 0.0 < level < 1.0:
            raise MestraError("", "level is a coverage in (0, 1)", name)
        method = str(entry["method"])
        if not method:
            raise MestraError("", "method is one sentence", name)
        made.update(uncertainty=band, level=level, method=method)
    return made

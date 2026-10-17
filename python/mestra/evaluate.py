"""Evaluating served slots, and the record a viewer asks for.

`evaluate(ds, inputs)` gives a new dataset whose rows are the input
table's rows and whose served slots hold what their callables return;
with no inputs it evaluates on the file's own rows. `prediction(ds,
slot, inputs)` is one slot's record: for a stored slot its values and
the band stored beside it, for a served slot what its callable
returns.

A callable is called once per evaluation, with the table its `inputs`
declare (any parameter, scalar or field, each with a leading `row`
axis), or, when the file declares none, with every design, condition
and time parameter. When a callable declares `inputs` and its own
dictionary declares the columns it reads (as `affine` does), the two
sets must be equal. A band slot takes its output's uncertainty and
writes the record's level and method; a derivative slot names an
ordinary output; the record's float64 values are written into the
slot's dtype.

The evaluated dataset carries no callables and no `/private`: it is a
new set of numbers, not the file the callables came from.
"""

from __future__ import annotations

import copy
from typing import Any

import numpy as np

from .callables import Affine, InputTable, Prediction, input_table
from .errors import MestraError
from .model import (
    Dataset,
    Label,
    MemorySource,
    Mesh,
    NamedArray,
    Parameter,
    Slot,
)

__all__ = ["evaluate", "prediction"]


def evaluate(ds: Dataset, inputs: Any = None) -> Dataset:
    """Evaluate every served slot.

    `inputs` is an input table (a mapping of name to column, an
    `InputTable`, or a two-dimensional array with names) holding a
    column for every parameter and label of the file and for whatever
    the callables read, or None to evaluate on the file's own rows.
    """
    table = None if inputs is None else input_table(inputs)
    rows = ds.row_count if table is None else table.row_count
    out = Dataset(writer=ds.writer, created=ds.created)
    for key in ("title", "license", "references", "source",
                "generalisation_group"):
        setattr(out, key, getattr(ds, key))
    out.categories = copy.deepcopy(ds.categories)
    out._extra = dict(ds._extra)
    out.notes.update(dict(ds.notes))
    out._row_count = rows
    for name, parameter in ds.parameters.items():
        values = _column(ds, table, name, parameter.values)
        out.parameters[name] = Parameter(
            name, parameter.role, units=parameter.units,
            lower=parameter.lower, upper=parameter.upper,
            run_group=parameter.run_group,
            data=MemorySource(_as(values, parameter.dtype)),
            extra=dict(parameter._extra))
    for name, label in ds.labels.items():
        reader = label.names if label.role == "id" else label.codes
        values = _column(ds, table, name, reader)
        out.labels[name] = Label(
            name, label.role, category=label.category,
            data=MemorySource(_as(values, label.dtype)),
            extra=dict(label._extra), dataset=out)
    records = _records(ds, table)
    for name, slot in ds.scalars.items():
        dict.__setitem__(out.scalars, name,
                         _fill(slot, records, rows, out))
    if ds.mesh is not None:
        mesh = Mesh(ds.mesh.kind, n_nodes=ds.mesh.n_nodes,
                    n_cells=ds.mesh.n_cells,
                    stored_support_id=ds.mesh._stored_support_id,
                    extra=dict(ds.mesh._extra))
        mesh._dataset = out
        for which, source in ds.mesh._cells.items():
            mesh._cells[which] = None if source is None else \
                MemorySource(source.read())
        if ds.mesh.coordinates is not None:
            mesh.coordinates = _fill(ds.mesh.coordinates, records, rows,
                                     out)
        for group, into in ((ds.mesh.node_arrays, mesh.node_arrays),
                            (ds.mesh.cell_arrays, mesh.cell_arrays)):
            for name, slot in group.items():
                dict.__setitem__(into, name,
                                 _fill(slot, records, rows, out))
        out.mesh = mesh
    return out


def prediction(ds: Dataset, slot_name: str,
               inputs: Any = None) -> Prediction:
    """The record of one slot: its mean and, when it has one, its band.

    `slot_name` is a scalar's name, or `node_arrays/<name>`,
    `cell_arrays/<name>` or `coordinates` (a bare mesh array name is
    accepted when only one array has it). For a stored slot the mean is
    its values per row and the band is the stored band whose `of` names
    it; `inputs` is refused. For a served slot its callable is called
    on `inputs`, or on the file's own rows, and its record returned. A
    band or std slot is refused: name its base.
    """
    slot, group = _find(ds, slot_name)
    if slot.statistic in ("band", "std"):
        raise MestraError(
            "", "%s is a %s; ask for the slot it is about, %s"
            % (slot_name, slot.statistic, slot.of), slot.path)
    if not slot.served:
        if inputs is not None:
            raise MestraError(
                "", "%s holds data, so it has no inputs to take; leave "
                "inputs out" % slot_name, slot.path)
        mean = _per_row(slot, ds.row_count)
        for other in group.values():
            if other.statistic == "band" and other.of == slot.name and \
                    not other.served:
                return Prediction(mean, _per_row(other, ds.row_count),
                                  level=other.level, method=other.method)
        return Prediction(mean)
    table = None if inputs is None else input_table(inputs)
    identifier = slot.callable_id or ""
    record = _call(ds, identifier, table).get(slot.output or slot.name)
    if not isinstance(record, Prediction):
        raise MestraError(
            "E14", "the callable %s returned no output called %r"
            % (identifier, slot.output), slot.path)
    return record


# ------------------------------------------------------------- pieces

def _column(ds: Dataset, table: InputTable | None, name: str,
            reader: Any) -> np.ndarray:
    if table is None:
        return np.asarray(reader().values)
    if name not in table:
        raise MestraError(
            "", "the input table has no column %r; it carries every "
            "parameter and label of the file, and whatever the callables "
            "read" % name)
    return np.asarray(table[name].values)


def _as(values: np.ndarray, dtype: Any) -> np.ndarray:
    if dtype is None or values.dtype.kind in "US":
        return values
    if np.dtype(dtype).kind in "iu" and values.dtype.kind == "f":
        exact = values.astype(dtype)
        if not np.array_equal(exact, values):
            raise MestraError(
                "E20", "an integer column was given values that are not "
                "integers")
        return exact
    return values.astype(dtype)


def _records(ds: Dataset, table: InputTable | None) -> dict[str, Any]:
    wanted = sorted({s.callable_id or "" for s in ds._slots().values()
                     if s.served})
    return {identifier: _call(ds, identifier, table)
            for identifier in wanted}


def _call(ds: Dataset, identifier: str,
          table: InputTable | None) -> dict[str, Any]:
    """Call one callable on the table its inputs declare."""
    if identifier not in ds.callables:
        raise MestraError(
            "E14", "the file holds no callable called %r" % identifier,
            "callables/" + identifier)
    obj = ds.callables[identifier]
    declared = ds._callable_inputs.get(identifier)
    if declared is not None and isinstance(obj, Affine) and \
            frozenset(obj.keys) != declared:
        raise MestraError(
            "", "the callable %s declares the inputs %s and its dictionary "
            "reads %s; the two sets must be equal"
            % (identifier, ", ".join(sorted(declared)),
               ", ".join(sorted(obj.keys))), "callables/" + identifier)
    if declared is None:
        names = [n for n, p in ds.parameters.items()
                 if p.role in ("design", "condition", "time")]
    else:
        names = sorted(declared, key=lambda n: n.encode("utf-8"))
    if table is None:
        given = input_table(ds, names)
    else:
        missing = [n for n in names if n not in table]
        if missing:
            raise MestraError(
                "", "the input table has no column %s, which the callable "
                "%s reads" % (", ".join(missing), identifier),
                "callables/" + identifier)
        given = input_table(table, names)
    records = obj(given)
    if not isinstance(records, dict):
        raise MestraError(
            "", "a callable returns one Prediction per output, as a "
            "mapping; %s returned %s" % (identifier,
                                         type(records).__name__),
            "callables/" + identifier)
    return records


def _fill(slot: Slot, records: dict[str, Any], rows: int,
          out: Dataset) -> Slot:
    made = copy.copy(slot)
    made._extra = dict(slot._extra)
    made._dataset = out
    if not slot.served:
        if slot._data is not None:
            if slot.varies == "row" and int(slot._data.shape[0]) != rows:
                raise MestraError(
                    "E16", "this slot holds %d rows of data and the input "
                    "table has %d; evaluate on the file's own rows, or on "
                    "a file whose row-varying slots are all served"
                    % (int(slot._data.shape[0]), rows), slot.path)
            made._data = MemorySource(slot._data.read())
        return made
    record = records[slot.callable_id or ""].get(slot.output or slot.name)
    if not isinstance(record, Prediction):
        raise MestraError(
            "E14", "the callable %s returned no output called %r"
            % (slot.callable_id, slot.output), slot.path)
    if slot.statistic == "band":
        if record.uncertainty is None:
            raise MestraError(
                "E12", "this band takes the uncertainty of output %r, and "
                "the callable returned none" % slot.output, slot.path)
        values = record.uncertainty
        made.level = record.level
        made.method = record.method
    elif slot.statistic == "std":
        raise MestraError("E12", "a std is stored, never served",
                          slot.path)
    else:
        values = record.mean
    dtype = slot.dtype if slot.dtype is not None else np.dtype("<f8")
    array = np.asarray(values, dtype="<f8").astype(dtype)
    _check_shape(slot, array, rows)
    made._data = MemorySource(array)
    made.source = "data"
    made.output = None
    made._dims = None
    return made


def _check_shape(slot: Slot, array: np.ndarray, rows: int) -> None:
    if array.shape[:1] != (rows,):
        raise MestraError(
            "E16", "a callable returns one entry per row of its table; "
            "this one returned %s for %d rows" % (array.shape, rows),
            slot.path)
    if slot.location == "row":
        if array.ndim != 1:
            raise MestraError(
                "E04", "a scalar takes one value per row; the callable "
                "returned %s" % (array.shape,), slot.path)
        return
    if array.ndim != 3:
        raise MestraError(
            "E04", "a field is (row, %s, component); the callable returned "
            "%s" % (slot.location, array.shape), slot.path)
    if array.shape[-1] != slot.components:
        raise MestraError(
            "E31", "the slot has %s components and the callable returned %d"
            % (slot.components, array.shape[-1]), slot.path)
    dataset = slot._dataset
    mesh = dataset.mesh if dataset is not None else None
    if mesh is not None:
        width = mesh.n_nodes if slot.location == "node" else mesh.n_cells
        if array.shape[1] != width:
            raise MestraError(
                "E05", "the mesh has %d %ss and the callable returned %d"
                % (width, slot.location, array.shape[1]), slot.path)


def _find(ds: Dataset, name: str) -> tuple[Slot, dict[str, Slot]]:
    if name.startswith("scalars/"):
        name = name[len("scalars/"):]
    if name.startswith("mesh/"):
        name = name[len("mesh/"):]
    if name in ds.scalars:
        return ds.scalars[name], dict(ds.scalars.items())
    mesh = ds.mesh
    if mesh is not None:
        if name == "coordinates" and mesh.coordinates is not None:
            return mesh.coordinates, {}
        for prefix, group in (("node_arrays/", mesh.node_arrays),
                              ("cell_arrays/", mesh.cell_arrays)):
            if name.startswith(prefix) and name[len(prefix):] in group:
                return group[name[len(prefix):]], dict(group.items())
        found = [(g[name], dict(g.items())) for g in (mesh.node_arrays,
                                                      mesh.cell_arrays)
                 if name in g]
        if len(found) == 1:
            return found[0]
        if len(found) > 1:
            raise MestraError(
                "", "a node array and a cell array are both called %r; "
                "name node_arrays/%s or cell_arrays/%s" % (name, name, name))
    raise MestraError("", "this dataset has no slot called %r" % name)


def _per_row(slot: Slot, rows: int) -> np.ndarray:
    values: NamedArray = slot.read(rows=slice(0, rows))
    return np.asarray(values.values, dtype="<f8")

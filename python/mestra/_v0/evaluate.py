"""Evaluating a file's callables on a keys table.

Section 10: evaluating a file on a keys table yields a file with the
same slots, now holding data. Distillation is that operation on a
grid.

What the result carries under `/callables`. Section 10 says only
that the slots now hold data, and that sentence can be read three
ways: leave no `/callables` group, leave it present and empty, or
leave the whole callable with its dictionary. All three
conform -- section 13 lets a container group be absent or present
and empty, and no rule forbids a callable nothing references -- so
the sentence alone does not settle it and another one has to.

Section 12 is that sentence: "A distilled lookup table is stored
data and therefore public; the callable that produced it, its
history, and its validation records are not." The evaluated file is
the distilled table. The callable is the thing section 12 says is
not part of it, so this implementation leaves no `/callables` group
at all: the result is a plain data file with the same keys, the same
supports and the same slot attributes, and every slot's `source` is
`data`.

Section 7 of docs/api-conventions.md settled it for the four
implementations in the same words: "the `/callables` group is absent
from an evaluated file, not present and empty".

Section 13's rule that "a writer reproducing a file it read keeps
whichever of the two it found" is about a round trip and not about
this: evaluation does not reproduce the file it read, it produces a
different file, and a group that would be empty may be absent.

Nothing here reads `/private` or copies it. An evaluated file is a
new file and not a round trip of the one the callables came from;
`read` and `write` are what preserve a producer's own records.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

import numpy as np

from ..errors import MestraError
from .callables import Prediction, keys_table, table_length
from .model import (
    ArraySlot,
    Dataset,
    Key,
    MemorySource,
    ScalarSlot,
    Storage,
)

__all__ = ["evaluate"]


def evaluate(dataset: Dataset, table: Any,
             names: list[str] | None = None) -> Dataset:
    """Evaluate every callable slot on a keys table.

    `table` is a keys table as section 26 defines it for Python: a
    mapping from key name to a one-dimensional array, or a
    two-dimensional array of shape (rows, keys) together with
    `names` in the file's key order.

    The result is a new dataset whose rows are the table's rows and
    whose callable slots hold the values the callables produced.
    Every slot's `source` is `data`, and the result carries no
    callables and no `/private`: section 12 says the distilled table
    is public and that the callable that produced it, its history
    and its validation records are not. The module docstring has the
    argument in full.
    """
    columns = keys_table(table, names)
    rows = table_length(columns)
    missing = [n for n in dataset.key_names() if n not in columns]
    if missing:
        raise MestraError(
            "", "the keys table needs one column per key the file "
            "declares, in the file's key order; it has none for %s"
            % ", ".join(missing))

    out = Dataset(writer=dataset.writer, created=dataset.created,
                  format=dataset.format,
                  generalisation_group=dataset.generalisation_group,
                  notes=dataset.notes)
    out.n_rows = rows
    out.categories = copy.deepcopy(dataset.categories)
    out.extra = dict(dataset.extra)
    out.present = {name for name in dataset.present
                   if name != "callables"}

    for name in dataset.key_names():
        source = dataset.keys[name]
        out.keys[name] = Key(
            name, source.role, units=source.units, lower=source.lower,
            upper=source.upper, category=source.category,
            trajectory_group=source.trajectory_group,
            parent=source.parent, itemsize=source.itemsize,
            data=MemorySource(_column(columns[name], source)),
            extra=dict(source.extra))

    produced = _produce(dataset, columns)

    for name, slot in dataset.scalars.items():
        out.scalars[name] = _fill(slot, produced, rows, ScalarSlot)
    for name, support in dataset.supports.items():
        copied = copy.copy(support)
        copied.dataset = out
        copied.node_arrays = {}
        copied.cell_arrays = {}
        # The result stands on its own, so its arrays are in memory
        # and not still in the file the callables came from.
        copied._cells = {
            which: (None if source is None
                    else MemorySource(source.read()))
            for which, source in support._cells.items()}
        if support.coordinates is not None:
            copied.coordinates = _fill(support.coordinates, produced,
                                       rows, ArraySlot, copied)
        for where, arrays in (("node_arrays", support.node_arrays),
                              ("cell_arrays", support.cell_arrays)):
            into = getattr(copied, where)
            for slot_name, array in arrays.items():
                into[slot_name] = _fill(array, produced, rows,
                                        ArraySlot, copied)
        out.supports[name] = copied
    if dataset.has_row_support:
        out.row_support = dataset.row_support
    return out


def _column(values: Any, key: Key) -> np.ndarray:
    """A table column in the dtype the key's role requires."""
    array = np.asarray(values)
    if key.role in ("categorical", "group", "split", "status"):
        return array.astype("<i4", copy=False)
    if key.role == "id":
        if array.dtype.kind in "US":
            return array
        return array.astype("<i8", copy=False)
    return array.astype("<f8", copy=False)


def _produce(dataset: Dataset,
             columns: Mapping[str, np.ndarray]) -> dict[str, Any]:
    """Call each callable once, whatever number of slots it fills."""
    wanted = set()
    for slot in dataset.slots().values():
        if slot.is_callable:
            identifier = slot.callable_id or ""
            if identifier not in dataset.callables:
                raise MestraError(
                    "E14", "this slot names the callable %r and the "
                    "file does not hold it" % identifier, slot.name)
            wanted.add(identifier)
    return {name: dataset.callables[name](columns) for name in wanted}


def _fill(slot: Any, produced: Mapping[str, Any], rows: int,
          kind: Any, support: Any = None) -> Any:
    """One slot of the evaluated dataset."""
    made = copy.copy(slot)
    made.storage = Storage()
    made.extra = dict(slot.extra)
    if support is not None:
        made.support = support
    if not slot.is_callable:
        if slot.data is not None and "row" in slot.dims:
            have = int(slot.data.shape[0])
            if have != rows:
                raise MestraError(
                    "E16", "this slot holds %d rows of stored data and "
                    "the keys table has %d; evaluate a file whose "
                    "row-varying slots are all callables, or pass a "
                    "table of the same length" % (have, rows),
                    slot.name)
            made.data = MemorySource(slot.data.read())
        elif slot.data is not None:
            made.data = MemorySource(slot.data.read())
        return made
    values = produced[slot.callable_id or ""]
    output = slot.output or slot.name
    if output not in values:
        raise MestraError(
            "E14", "the callable %s produced no output called %r"
            % (slot.callable_id, output), slot.name)
    record = values[output]
    if not isinstance(record, Prediction):
        raise MestraError(
            "section 10", "a callable returns a Prediction per output; "
            "%s returned %s for %r"
            % (slot.callable_id, type(record).__name__, output),
            slot.name)
    # Section 10: which part of the record fills the slot is its
    # statistic. A band slot takes the uncertainty and, with it, the
    # level and the method the record states.
    if slot.statistic == "band":
        if record.uncertainty is None:
            raise MestraError(
                "E12", "this band slot takes the uncertainty of output "
                "%r and the callable %s returned none; a band without "
                "a level cannot be stored, so drop the slot or give "
                "the model a band" % (output, slot.callable_id),
                slot.name)
        array = record.uncertainty
        made.level = record.level
        made.method = record.method
    elif slot.statistic in (None, "value", "mean"):
        array = record.mean
    else:
        raise MestraError(
            "E12", "a callable serves value, mean and band slots; this "
            "one is %s" % slot.statistic, slot.name)
    array = np.asarray(array, dtype="<f8")
    _check_shape(slot, array, rows, kind)
    made.data = MemorySource(array)
    made.source = "data"
    made.output = None
    return made


def _check_shape(slot: Any, array: np.ndarray, rows: int,
                 kind: Any) -> None:
    if array.shape[:1] != (rows,):
        raise MestraError(
            "E16", "a callable returns one entry per table row; this "
            "one returned %s for %d rows" % (array.shape, rows),
            slot.name)
    if kind is ScalarSlot:
        if array.ndim != 1:
            raise MestraError(
                "E04", "a scalar slot takes one value per row; the "
                "callable returned %s" % (array.shape,), slot.name)
        return
    if array.ndim != len(slot.dims):
        raise MestraError(
            "E04", "this slot has the dimensions %s; the callable "
            "returned %s" % (", ".join(slot.dims), array.shape),
            slot.name)
    if array.shape[-1] != slot.components:
        raise MestraError(
            "E31", "this slot declares %d components and the callable "
            "returned %d" % (slot.components, array.shape[-1]),
            slot.name)
    support = slot.support
    if support is not None:
        width = (support.n_nodes if slot.location == "node"
                 else support.n_cells)
        if array.shape[-2] != width:
            raise MestraError(
                "E05", "this support has %d %ss and the callable "
                "returned %d" % (width, slot.location, array.shape[-2]),
                slot.name)

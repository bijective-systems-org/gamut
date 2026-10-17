"""Post-processing written against the format and nothing else.

Five operations that need no knowledge of where a file came from:
one slot as a prediction, its mean with its band, whether the slot
holds data or a callable serves it;
statistics of a field or a scalar, grouped by a label or a key;
integration of a field over a support or one region of it, with the
weights section 3 says are computed from the connectivity;
a time series at one node along a trajectory; and a split that
honours the unit of generalisation.

They work the same on solver output and on the result of evaluating
a callable, because both are the same file.

A name that is not in the file is the caller's mistake and is raised
without a rule identifier; the identifiers stay for findings about a
file.
"""

from __future__ import annotations

import math
import warnings
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np

from ..errors import MestraError
from .callables import Prediction, keys_table
from .model import ArraySlot, Dataset, Key, ScalarSlot, Support
from .weights import compute_weights, measures

__all__ = [
    "prediction",
    "Statistics",
    "field_statistics",
    "integrate",
    "time_series",
    "grouped_split",
    "split_leaks",
    "compute_weights",
    "find_array",
]


def __dir__() -> list[str]:
    """What this module offers, and not what it imported to do it."""
    return sorted(__all__)


# ----------------------------------------------------------- finding it

def find_array(dataset: Dataset, name: str,
               support: str | None = None) -> tuple[Support, ArraySlot]:
    """The support and slot an array name refers to.

    `name` may be "pressure" or "s0/pressure" or
    "node_arrays/pressure"; the support is named when more than one
    holds an array of that name.
    """
    if "/" in name and support is None:
        head, name = name.rsplit("/", 1)
        if head not in ("node_arrays", "cell_arrays"):
            support = head
    found = []
    for sname in dataset.support_names():
        if support is not None and sname != support:
            continue
        one = dataset.supports[sname]
        for slot_name, slot in one.arrays().items():
            if slot_name.rsplit("/", 1)[-1] == name:
                found.append((one, slot))
    if not found:
        raise MestraError(
            "", "no array called %r on %s; this file has %s" % (
                name, "support " + support if support
                else "any support", _listed(_array_names(dataset,
                                                         support))),
            name)
    if len(found) > 1:
        raise MestraError(
            "", "%d supports carry an array called %r; name the support "
            "as well, as in \"%s/%s\"" % (len(found), name,
                                          found[0][0].name, name), name)
    return found[0]


def _slot_by_name(dataset: Dataset, name: str
                  ) -> tuple[Support | None, Any]:
    """A scalar by name, or an array by `find_array`'s spellings."""
    if "/" not in name and name in dataset.scalars:
        return None, dataset.scalars[name]
    return find_array(dataset, name)


# ---------------------------------------------------------- prediction

def prediction(dataset: Dataset, slot: str,
               keys: Any = None) -> Prediction:
    """One slot as a prediction: its mean with its band.

    `slot` names a scalar or an array (as `find_array` spells it)
    whose statistic is `value` or `mean`, or none. For a stored slot
    the mean is its data and the band is the `band` slot at the same
    location that names it with `of`, if there is one; `keys` must
    then be omitted, because stored data has values on its own rows
    only. For a slot a callable serves, the callable is called on
    `keys`, or on the file's own key columns when `keys` is omitted,
    and its record for the slot's output is returned as it is
    (section 10). Either way the caller gets the same record and
    never has to know which it was.
    """
    support, found = _slot_by_name(dataset, slot)
    if found.statistic == "band":
        raise MestraError(
            "", "%r is the band of %r; name the base slot and the band "
            "comes with it" % (slot, found.of), slot)
    if found.statistic not in (None, "value", "mean"):
        raise MestraError(
            "", "%r holds the %s of %r, which is stored data about "
            "stored data and not a prediction; name the base slot"
            % (slot, found.statistic, found.of), slot)
    if found.is_callable:
        identifier = found.callable_id or ""
        if identifier not in dataset.callables:
            raise MestraError(
                "E14", "this slot names the callable %r and the file "
                "does not hold it" % identifier, slot)
        if keys is None:
            if not dataset.n_rows:
                raise MestraError(
                    "", "this file has no rows to evaluate %r on; pass "
                    "keys= with one column per key" % slot, slot)
            keys = {name: dataset.keys[name].read().values
                    for name in dataset.key_names()}
        records = dataset.callables[identifier](keys_table(keys))
        output = found.output or found.name
        if output not in records:
            raise MestraError(
                "E14", "the callable %s produced no output called %r"
                % (identifier, output), slot)
        record = records[output]
        if not isinstance(record, Prediction):
            raise MestraError(
                "section 10", "a callable returns a Prediction per "
                "output; %s returned %s" % (identifier,
                                             type(record).__name__),
                slot)
        return record
    if keys is not None:
        raise MestraError(
            "", "%r holds stored data, which has values on its own rows "
            "only; omit keys=, or name a slot a callable serves" % slot,
            slot)
    mean = np.asarray(found.read().values)
    band = _band_of(dataset, support, found)
    if band is None:
        return Prediction(mean)
    return Prediction(mean, np.asarray(band.read().values),
                      level=band.level, method=band.method)


def _band_of(dataset: Dataset, support: Support | None,
             base: Any) -> Any:
    """The band slot at the same location as `base` that names it."""
    candidates: list[Any]
    if support is None:
        candidates = list(dataset.scalars.values())
    else:
        arrays = (support.node_arrays if base.location == "node"
                  else support.cell_arrays)
        candidates = list(arrays.values())
    for slot in candidates:
        if slot.statistic == "band" and slot.of == base.name \
                and not slot.is_callable:
            return slot
    return None


def _array_names(dataset: Dataset, support: str | None) -> list[str]:
    out = []
    for sname in dataset.support_names():
        if support is not None and sname != support:
            continue
        for slot_name in dataset.supports[sname].arrays():
            out.append(slot_name.rsplit("/", 1)[-1])
    return sorted(set(out))


def _listed(names: list[str]) -> str:
    return ", ".join(names) if names else "none"


def _rows_of(dataset: Dataset, support: Support,
             slot: ArraySlot) -> np.ndarray:
    """The file row of each entry along a slot's leading dimension.

    In an unaligned file a row-varying array holds one entry per row
    referencing its support, in the file's row order (section 22).
    """
    if slot.varies != "row":
        raise MestraError(
            "", "this array varies along %s, not along the row "
            "(section 5)" % slot.varies, slot.name)
    return np.asarray(dataset.rows_on(support))


def _values(slot: ArraySlot) -> np.ndarray:
    values = np.asarray(slot.read().values)
    if slot.varies == "none":
        return values[None, ...]
    return values


# ------------------------------------------------------------ statistics

@dataclass
class Statistics:
    """Per-field statistics, per row and per group.

    `over` is what was aggregated: "node" or "cell" for an array,
    "row" for a scalar. `by` is the name of the label or key the
    statistics were grouped by, or None, and `groups` names each
    group in the order the tables hold them. `rows` holds the file
    row of each row of the tables, and is None for a scalar, whose
    tables hold one aggregate over the rows. Every table has the
    shape (rows, groups, components).
    """

    name: str
    units: str | None
    over: str
    by: str | None
    rows: np.ndarray | None
    groups: list[str] | None
    count: np.ndarray
    minimum: np.ndarray
    maximum: np.ndarray
    mean: np.ndarray
    std: np.ndarray

    def as_table(self, component: int = 0) -> list[dict[str, Any]]:
        """One dictionary per row and group.

        The grouping column is called after the label or key it
        groups by, and there is no such column when the statistics
        were not grouped.
        """
        out = []
        rows = self.rows if self.rows is not None else [None]
        for at, row in enumerate(rows):
            for group in range(self.count.shape[1]):
                one: dict[str, Any] = {}
                if row is not None:
                    one["row"] = int(row)
                if self.by is not None and self.groups is not None:
                    one[self.by] = self.groups[group]
                one.update({
                    "count": int(self.count[at, group, component]),
                    "min": float(self.minimum[at, group, component]),
                    "max": float(self.maximum[at, group, component]),
                    "mean": float(self.mean[at, group, component]),
                    "std": float(self.std[at, group, component]),
                })
                out.append(one)
        return out

    def as_text(self, component: int = 0) -> str:
        """The same table, as lines a person can read."""
        table = self.as_table(component)
        if not table:
            return ""
        columns = list(table[0])
        widths = [max(len(c), max(len(_cell(r[c])) for r in table))
                  for c in columns]
        lines = ["  ".join(c.rjust(w) for c, w in zip(columns, widths))]
        for row in table:
            lines.append("  ".join(_cell(row[c]).rjust(w)
                                   for c, w in zip(columns, widths)))
        return "\n".join(lines)

    def __str__(self) -> str:
        head = "%s%s over %ss" % (
            self.name, " [%s]" % self.units if self.units else "",
            self.over)
        if self.by:
            head += " by %s" % self.by
        return "%s\n%s" % (head, self.as_text())


def _cell(value: Any) -> str:
    if isinstance(value, float):
        return "%.6g" % value
    return str(value)


def field_statistics(dataset: Dataset, slot: str, *,
                     by: str | None = None,
                     support: str | None = None) -> Statistics:
    """Statistics of a field or a scalar, per row and per group.

    `slot` names an array on a support, or a scalar. For an array
    the statistics are of each row over the nodes or the cells, and
    `by` names a label array at the same location that groups them.
    For a scalar there is one value per row, so the statistics are
    over the rows, and `by` names a categorical, group, split or
    status key that groups them.

    The output is keyed by the name of whatever `by` named, and has
    no grouping column at all when `by` is not given. Non-finite
    values are left out of the count and of the statistics, which is
    how this format spells missing data (W03).
    """
    if support is None and slot in dataset.scalars:
        return _scalar_statistics(dataset, dataset.scalars[slot], by)
    one, found = find_array(dataset, slot, support)
    values = _values(found)
    rows = (_rows_of(dataset, one, found) if found.varies == "row"
            else np.arange(values.shape[0]))
    if "draw" in found.dims:
        raise MestraError(
            "", "this slot holds draws (section 9); take the statistics "
            "of the quantity it is the draws of, or select a draw first",
            found.name)
    groups, names = _regions(dataset, one, found, by)
    count, low, high, mean, std = _aggregate(values, groups, axis=1)
    return Statistics(found.name, found.units, found.location, by, rows,
                      names, count, low, high, mean, std)


def _scalar_statistics(dataset: Dataset, slot: ScalarSlot,
                       by: str | None) -> Statistics:
    """P5: dataset 3 is nothing but scalars, and the one verb that
    suits it should apply to it."""
    values = np.asarray(slot.read().values).reshape(-1, 1)[None, :, :]
    groups, names = _key_groups(dataset, by, values.shape[1])
    count, low, high, mean, std = _aggregate(values, groups, axis=1)
    return Statistics(slot.name, slot.units, "row", by, None, names,
                      count, low, high, mean, std)


def _aggregate(values: np.ndarray, groups: list[Any], axis: int
               ) -> tuple[np.ndarray, ...]:
    shape = (values.shape[0], len(groups), values.shape[-1])
    count = np.zeros(shape, dtype="i8")
    low = np.full(shape, np.nan)
    high = np.full(shape, np.nan)
    mean = np.full(shape, np.nan)
    std = np.full(shape, np.nan)
    for at, where in enumerate(groups):
        part = values[:, where, :]
        good = np.isfinite(part)
        count[:, at, :] = good.sum(axis=axis)
        if not part.shape[1]:
            continue
        masked = np.where(good, part, np.nan)
        # A row with nothing finite in it keeps the NaN it starts
        # with; numpy would say so with a warning, and the count
        # already says it.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            low[:, at, :] = np.nanmin(masked, axis=axis)
            high[:, at, :] = np.nanmax(masked, axis=axis)
            mean[:, at, :] = np.nanmean(masked, axis=axis)
            std[:, at, :] = np.nanstd(masked, axis=axis)
    return count, low, high, mean, std


def _regions(dataset: Dataset, support: Support, slot: ArraySlot,
             by: str | None) -> tuple[list[Any], list[str] | None]:
    """The node or cell indices of each group, and its name."""
    width = (support.n_nodes if slot.location == "node"
             else support.n_cells)
    if by is None:
        return [np.arange(width)], None
    arrays = (support.node_arrays if slot.location == "node"
              else support.cell_arrays)
    if by not in arrays:
        raise MestraError(
            "", "no label called %r on the %ss of support %s; this "
            "support has %s" % (by, slot.location, support.name,
                                _listed(sorted(arrays))), by)
    if arrays[by].varies != "none":
        raise MestraError(
            "", "this label varies along %s; only a label that does not "
            "vary groups a whole field" % arrays[by].varies, by)
    values = np.asarray(arrays[by].read().values)
    flat = values.reshape(-1)
    table = dataset.categories.get(arrays[by].category or "")
    ids = sorted({int(v) for v in flat})
    names = [table[i] if table and 0 <= i < len(table) else str(i)
             for i in ids]
    return [np.flatnonzero(flat == i) for i in ids], names


def _key_groups(dataset: Dataset, by: str | None, rows: int
                ) -> tuple[list[Any], list[str] | None]:
    """The rows of each group of a key, and its name."""
    if by is None:
        return [np.arange(rows)], None
    key = dataset.keys.get(by)
    if key is None:
        raise MestraError(
            "", "no key called %r; this file has %s"
            % (by, _listed(dataset.key_names())), by)
    values = np.asarray(key.read().values).reshape(-1)
    table = dataset.categories.get(key.category or "")
    ids = sorted(set(values.tolist()))
    names = [table[int(i)] if table and 0 <= int(i) < len(table)
             else str(i) for i in ids]
    return [np.flatnonzero(values == i) for i in ids], names


# ----------------------------------------------------------- integration

def integrate(dataset: Dataset, slot: str, *, weight: str | None = None,
              support: str | None = None, by: str | None = None,
              region: str | None = None) -> np.ndarray:
    """Integrate a field over a support, or over one region of it.

    The weights are the weight array at the slot's location on its
    support. Section 3 says such an array is computed from the
    connectivity and never imported, so when the file has none this
    computes one, says so, and does not store it;
    `mestra.post.compute_weights(support, location)` stores one.
    `weight=` names another array to use instead.

    The result has the shape (rows, components), and its units are
    the field's times the weight's.
    """
    one, found = find_array(dataset, slot, support)
    arrays = (one.node_arrays if found.location == "node"
              else one.cell_arrays)
    if weight is None:
        w = _default_weights(one, found)
    else:
        if weight not in arrays:
            raise MestraError(
                "", "no array called %r on the %ss of support %s; this "
                "support has %s" % (weight, found.location, one.name,
                                    _listed(sorted(arrays))), weight)
        measure = arrays[weight]
        if measure.role != "weight":
            raise MestraError(
                "E02", "%r has the role %s; integration takes an array "
                "with the role weight, which "
                "post.compute_weights(support, %r) computes"
                % (weight, measure.role, found.location), weight)
        w = np.asarray(measure.read().values).reshape(-1)
    values = _values(found)
    where: Any = slice(None)
    if by is not None:
        groups, names = _regions(dataset, one, found, by)
        if region is None:
            raise MestraError(
                "", "name the region to integrate over with region=, "
                "one of %s" % _listed(names or []), by)
        if names is None or region not in names:
            raise MestraError(
                "", "no region called %r; the label %r has %s"
                % (region, by, _listed(names or [])), by)
        where = groups[names.index(region)]
    part = values[:, where, :]
    return np.nansum(part * w[where].reshape(1, -1, 1), axis=1)


def _default_weights(support: Support, slot: ArraySlot) -> np.ndarray:
    """The support's weight array, or one computed on the spot."""
    arrays = (support.node_arrays if slot.location == "node"
              else support.cell_arrays)
    for found in arrays.values():
        if found.role == "weight" and found.data is not None:
            return np.asarray(found.read().values).reshape(-1)
    values = measures(support, slot.location)[0]
    warnings.warn(
        "support %s carries no weight array at the %ss, so the %s "
        "measure was computed from the connectivity for this call and "
        "not stored; post.compute_weights(support, %r) stores one"
        % (support.name, slot.location, slot.location, slot.location),
        stacklevel=3)
    return values


# ----------------------------------------------------------- time series

def time_series(dataset: Dataset, slot: str, node: int,
                trajectory: Any = None, *, component: int = 0,
                support: str | None = None
                ) -> tuple[np.ndarray, np.ndarray]:
    """One node's history along a trajectory.

    A trajectory is the set of rows sharing one value of the group
    the time key names as its trajectory_group (section 7). The
    result is the times and the values, in increasing time.
    """
    times = dataset.keys_of_role("time")
    if not times:
        raise MestraError(
            "", "this file declares no time key, so it holds no "
            "trajectory (section 7)")
    time = times[0]
    t = np.asarray(time.read().values)
    rows = np.arange(dataset.n_rows)
    if time.trajectory_group:
        group = dataset.keys.get(time.trajectory_group)
        if group is None:
            raise MestraError(
                "E39", "the time key names the trajectory group %r, "
                "and the file has no such key" % time.trajectory_group,
                time.name)
        labels = np.asarray(group.read().values)
        table = dataset.categories.get(group.category or "")
        if trajectory is None:
            raise MestraError(
                "", "name the trajectory, one of %s"
                % _listed(_trajectories(labels, table)), group.name)
        wanted = trajectory
        if isinstance(trajectory, str):
            if table is None:
                raise MestraError(
                    "", "the group key %r has no category table, so "
                    "name the trajectory by its id, one of %s"
                    % (group.name, _listed(_trajectories(labels, None))),
                    group.name)
            wanted = table.id_of(trajectory)
        rows = np.flatnonzero(labels == wanted)
    one, found = find_array(dataset, slot, support)
    values = _values(found)
    if found.varies == "row":
        on_support = _rows_of(dataset, one, found)
        at = [int(np.flatnonzero(on_support == r)[0]) for r in rows
              if r in on_support]
    else:
        at = [0] * len(rows)
    order = np.argsort(t[rows], kind="stable")
    rows = rows[order]
    at = [at[i] for i in order]
    index: list[Any] = [np.asarray(at), node, component]
    if "draw" in found.dims:
        index.insert(1, slice(None))
    return t[rows], values[tuple(index)]


def _trajectories(labels: np.ndarray, table: Any) -> list[str]:
    ids = sorted({int(v) for v in labels.reshape(-1)})
    return [table[i] if table and 0 <= i < len(table) else str(i)
            for i in ids]


# -------------------------------------------------------------- splitting

def split_leaks(dataset: Dataset,
                split: str | None = None) -> dict[Any, list[Any]]:
    """The generalisation units a split places on both sides (W01).

    Keyed by the unit's category name (its integer when the unit key
    has no table), each with the names of the split parts it lies in,
    sorted. An empty result means the split is a generalisation test;
    a file with no unit of generalisation, or no split key, is
    refused rather than answered with an empty result that would say
    the same thing.
    """
    unit = dataset.generalisation_group
    if not unit or unit not in dataset.keys:
        raise MestraError(
            "E39", "this file names no unit of generalisation, so "
            "nothing can leak across its split; call "
            "set_generalisation_group first", "/")
    if split is not None:
        if split not in dataset.keys:
            raise MestraError(
                "", "no key called %r; this file has %s"
                % (split, _listed(dataset.key_names())), split)
        keys = [dataset.keys[split]]
    else:
        keys = dataset.keys_of_role("split")
    if not keys:
        raise MestraError(
            "E03", "this file declares no key of role split, so there "
            "is no split for a unit to leak across", "/keys")
    labels = np.asarray(dataset.keys[unit].read().values)
    out: dict[Any, list[Any]] = {}
    table = dataset.categories.get(dataset.keys[unit].category or "")
    for key in keys:
        parts = dataset.categories.get(key.category or "")
        values = np.asarray(key.read().values)
        for one in np.unique(labels):
            sides = np.unique(values[labels == one])
            if len(sides) > 1:
                out[_entry(table, one)] = sorted(
                    (_entry(parts, s) for s in sides), key=str)
    return out


def _entry(table: Any, value: Any) -> Any:
    """A category's name, or its integer when there is no table."""
    if table is not None and 0 <= int(value) < len(table):
        return table[int(value)]
    return int(value)


def grouped_split(dataset: Dataset,
                  fractions: Mapping[str, float] | None = None,
                  seed: int = 0) -> dict[str, np.ndarray]:
    """Split the rows by the unit of generalisation (section 31).

    Whole units move together, so no unit lands on both sides. The
    result maps each part's name to the file rows in it, in the order
    of the part names as UTF-8 bytes. `fractions` names each part and
    gives it a fraction, normalised by their sum, so 8 and 2 mean
    what 0.8 and 0.2 mean; it defaults to 80 per cent training and 20
    per cent test. `seed` defaults to 0.

    Section 31 is the algorithm, not this implementation: the units
    are ordered by their category names as bytes, one draw per unit
    comes from splitmix64 seeded with `seed`, the units are sorted by
    their draw, and the parts take consecutive blocks of them, sized
    by largest remainder. So one seed names one split in all four
    languages, which a language shuffling with its own generator
    cannot promise.

    Every named part gets at least one unit whenever there are at
    least as many units as parts; fewer units than that cannot be
    divided into the parts asked for, and the call is refused rather
    than returning an empty part to score a model on. So is a
    negative fraction, and a set of fractions that sums to zero.

    A file that names no unit of generalisation cannot be split this
    way and the call is refused: a split by row would score the model
    on a case it has already seen.
    """
    unit = dataset.generalisation_group
    if not unit or unit not in dataset.keys:
        raise MestraError(
            "W01", "this file names no unit of generalisation, so a "
            "split cannot honour one; a split by row would put rows "
            "of one case on both sides. Declare one with "
            "set_generalisation_group(name)")
    parts = dict(fractions or {"train": 0.8, "test": 0.2})
    if not parts or sum(parts.values()) <= 0 or \
            any(f < 0 for f in parts.values()):
        raise MestraError(
            "", "the fractions must name at least one part, none of "
            "them negative, and add to more than zero")
    key = dataset.keys[unit]
    labels = np.asarray(key.read().values).reshape(-1)
    units = _units_in_order(dataset, key, labels)
    if len(units) < len(parts):
        raise MestraError(
            "", "%r has %d unit(s) of generalisation and this asks for "
            "%d parts (%s); a part with no unit in it is not a test. "
            "Ask for fewer parts, or split a file with more units"
            % (unit, len(units), len(parts), ", ".join(parts)), unit)
    draws = _splitmix64(seed, len(units))
    shuffled = [units[at][1] for at in
                sorted(range(len(units)),
                       key=lambda at: (draws[at], units[at][0]))]
    names = sorted(parts, key=lambda name: name.encode("utf-8"))
    sizes = _part_sizes(len(units), [parts[name] for name in names])
    out: dict[str, np.ndarray] = {}
    at = 0
    for name, take in zip(names, sizes):
        mine = shuffled[at:at + take]
        at += take
        out[name] = np.flatnonzero(np.isin(labels, mine))
    return out


def _units_in_order(dataset: Dataset, key: Key,
                    labels: np.ndarray) -> list[tuple[bytes, int]]:
    """The distinct ids a group key holds, with their names, in order.

    The order is the category names as UTF-8 byte strings, and not
    the table's: two files that hold the same units in tables written
    in two orders must split the same way (section 31). An id no
    table names sorts under its own digits.
    """
    table = dataset.categories.get(key.category or "")
    named = []
    for one in {int(value) for value in labels}:
        name = (table[one] if table is not None and 0 <= one < len(table)
                else str(one))
        named.append((str(name).encode("utf-8"), one))
    return sorted(named)


def _splitmix64(seed: int, count: int) -> list[int]:
    """`count` draws of section 31's generator, seeded with `seed`.

    Sixty-four bits of state, every operation on unsigned 64-bit
    integers and every shift logical. The state starts at the seed
    and the first draw is what the first update returns, so the seed
    itself is never a draw.
    """
    mask = (1 << 64) - 1
    state = seed & mask
    draws = []
    for _ in range(count):
        state = (state + 0x9E3779B97F4A7C15) & mask
        z = state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & mask
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & mask
        draws.append(z ^ (z >> 31))
    return draws


def _part_sizes(units: int, fractions: list[float]) -> list[int]:
    """Whole units per part, the parts already in name order.

    Largest remainder first: the base size is the floor of the part's
    exact share and what is left over goes one each to the largest
    remainders, ties by name. Then the floor of one: while some part
    has no unit, the part with the fewest takes one from the part
    with the most, ties by name again. A part with no unit in it is
    not a test set, and with at least as many units as parts some
    part always has one to give (section 31).
    """
    total = sum(fractions)
    exact = [units * (f / total) for f in fractions]
    take = [math.floor(one) for one in exact]
    order = sorted(range(len(take)),
                   key=lambda at: (-(exact[at] - take[at]), at))
    for at in order[:units - sum(take)]:
        take[at] += 1
    while min(take) == 0:
        fewest = min(range(len(take)), key=lambda at: (take[at], at))
        most = max(range(len(take)), key=lambda at: (take[at], -at))
        take[most] -= 1
        take[fewest] += 1
    return take

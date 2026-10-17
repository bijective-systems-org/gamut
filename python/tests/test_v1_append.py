"""Appending rows in place.

The pattern a family store uses: write three rows, append a one-row
dataset that replaces a row by its id, then append a row that brings a
new status entry and a new member with its coordinates instance. The
file must then say what one write of all the rows says, and rewriting
it compacts what the appends left.
"""

from __future__ import annotations

import hashlib
import os

import h5py
import numpy as np
import pytest

from tests.v1_cases import (
    QUAD_CONNECTIVITY,
    QUAD_OFFSETS,
    QUAD_TYPES,
    QUAD_XY,
    content,
    lib,
)

pytestmark = pytest.mark.filterwarnings("error")

#: Every run a test may write: id, member, mach, status, cl.
RUNS = {
    "a@0.5": ("a", 0.5, "converged", 0.20),
    "b@0.5": ("b", 0.5, "converged", 0.25),
    "b@0.8": ("b", 0.8, "converged", 0.35),
    "b@0.5'": ("b", 0.5, "converged", 0.27),     # b@0.5 computed again
    "c@0.8": ("c", 0.8, "failed", 0.30),
}

#: Each member's geometry: the quad mesh scaled.
SCALE = {"a": 1.0, "b": 1.1, "c": 1.2}


def rows(ids, members=None, statuses=None):
    """A dataset of these runs, built like a whole file: its tables
    hold the members and statuses it is given (default: those its rows
    use, in order of first use)."""
    picked = [RUNS[i] for i in ids]
    names = [i.rstrip("'") for i in ids]
    members = members or list(dict.fromkeys(p[0] for p in picked))
    statuses = statuses or list(dict.fromkeys(p[2] for p in picked))
    ds = lib.Dataset(writer="family store", created="2026-10-16T00:00:00Z")
    ds.add_label("run", names, "id")
    ds.add_label("member", [members.index(p[0]) for p in picked], "group",
                 categories=members)
    ds.set_generalisation_group("member")
    ds.add_label("status", [statuses.index(p[2]) for p in picked],
                 "status", categories=statuses)
    ds.add_parameter("mach", [p[1] for p in picked], "condition", "1")
    ds.add_scalar("cl", [p[3] for p in picked], "1")
    ds.add_constant("s_ref", 2.0, "m2")
    coordinates = np.stack([QUAD_XY * SCALE[m] for m in members])
    mesh = ds.set_mesh((QUAD_TYPES, QUAD_OFFSETS, QUAD_CONNECTIVITY),
                       coordinates=coordinates, units="m",
                       dims=("group:member", "node", "component"))
    mesh.add_node_array("face", [1, 1, 2, 1, 1, 2], None, ("node",),
                        role="label")
    pressure = np.array([[p[3] * 100.0 + n for n in range(6)]
                         for p in picked])
    mesh.add_node_array("pressure", pressure, "Pa", ("row", "node"))
    mesh.add_cell_array("separated", [[int(p[3] > 0.3)] * 2
                                      for p in picked], None,
                        ("row", "cell"), role="label")
    return ds


def digest(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def test_the_family_store_pattern(tmp_path):
    path = str(tmp_path / "store.mes")
    lib.write(rows(["a@0.5", "b@0.5", "b@0.8"]), path)

    written = lib.append(rows(["b@0.5'"]), path, replace_by="run")
    assert written == 1
    with lib.read(path) as ds:
        assert ds.row_count == 3
        assert ds.scalars["cl"].read().values.tolist() == [0.2, 0.27, 0.35]

    written = lib.append(rows(["c@0.8"]), path, replace_by="run")
    assert written == 1
    with lib.read(path) as ds:
        assert ds.row_count == 4
        assert list(ds.labels["status"].table) == ["converged", "failed"]
        assert list(ds.labels["member"].table) == ["a", "b", "c"]
        assert list(ds.labels["member"].names().values) == ["a", "b", "b",
                                                            "c"]
        np.testing.assert_array_equal(
            ds.mesh.coordinates.read(rows=[3]).values[0], QUAD_XY * 1.2)
        assert (ds.parameters["mach"].lower,
                ds.parameters["mach"].upper) == (0.5, 0.8)

    once = str(tmp_path / "once.mes")
    lib.write(rows(["a@0.5", "b@0.5'", "b@0.8", "c@0.8"],
                   members=["a", "b", "c"],
                   statuses=["converged", "failed"]), once)
    assert content(path) == content(once)
    report = lib.validate(path)
    assert report.errors == []
    assert report.warning_ids == ["W02"]           # the failed row


def test_bounds_widen_to_cover_appended_values(tmp_path):
    path = str(tmp_path / "store.mes")
    lib.write(rows(["a@0.5"]), path)
    with lib.read(path) as ds:
        assert (ds.parameters["mach"].lower,
                ds.parameters["mach"].upper) == (0.5, 0.5)
    lib.append(rows(["b@0.8"]), path)
    with lib.read(path) as ds:
        assert (ds.parameters["mach"].lower,
                ds.parameters["mach"].upper) == (0.5, 0.8)
    assert "W04" not in lib.validate(path).warning_ids


def test_appending_several_rows_returns_the_rows_written(tmp_path):
    path = str(tmp_path / "store.mes")
    lib.write(rows(["a@0.5"]), path)
    assert lib.append(rows(["b@0.5", "b@0.8"]), path) == 2
    assert lib.append(rows(["b@0.5'", "c@0.8"]), path,
                      replace_by="run") == 2
    with lib.read(path) as ds:
        assert ds.row_count == 4
        assert list(ds.labels["run"].names().values) == [
            "a@0.5", "b@0.5", "b@0.8", "c@0.8"]


def test_a_longer_id_widens_its_dataset_and_a_rewrite_compacts(tmp_path):
    path = str(tmp_path / "store.mes")
    lib.write(rows(["a@0.5", "b@0.5"]), path)
    one = rows(["b@0.8"])
    long_id = "b@0.8-recomputed-with-a-much-longer-identifier"
    from mestra.model import MemorySource
    one.labels["run"]._data = MemorySource(np.array([long_id]))
    before = os.path.getsize(path)
    assert lib.append(one, path) == 1
    grown = os.path.getsize(path)
    with lib.read(path) as ds:
        assert ds.labels["run"].names().values.tolist()[-1] == long_id
        compact = str(tmp_path / "compact.mes")
        lib.write(ds, compact)
    assert lib.validate(path).errors == []
    assert content(compact) == content(path)
    assert os.path.getsize(compact) < grown and before < grown


@pytest.mark.parametrize("change, rule", [
    ("units", ""), ("duplicate", "E48"), ("replace_by", ""),
    ("geometry", ""), ("mesh", ""), ("extra scalar", ""),
])
def test_a_refused_append_leaves_the_file_as_it_was(tmp_path, change,
                                                    rule):
    path = str(tmp_path / "store.mes")
    lib.write(rows(["a@0.5", "b@0.5"]), path)
    before = digest(path)
    one = rows(["b@0.8"])
    replace_by = None
    if change == "units":
        one.scalars["cl"].units = "N"
    elif change == "duplicate":
        one = rows(["b@0.5'"])
    elif change == "replace_by":
        replace_by = "member"
    elif change == "geometry":
        one.mesh.coordinates._data.array[...] *= 2.0
    elif change == "mesh":
        one.mesh._cells["cell_connectivity"].array[0] = 2
    else:
        one.add_scalar("cd", [0.01], "1")
    with pytest.raises(lib.MestraError) as caught:
        lib.append(one, path, replace_by=replace_by)
    assert caught.value.rule == rule, caught.value
    assert digest(path) == before


def test_an_empty_append_writes_nothing(tmp_path):
    path = str(tmp_path / "store.mes")
    lib.write(rows(["a@0.5"]), path)
    empty = rows(["a@0.5"])
    for group in (empty.parameters, empty.labels):
        for item in group.values():
            item._data.array = item._data.array[:0]
    empty.scalars["cl"]._data.array = empty.scalars["cl"]._data.array[:0]
    for slot in empty.mesh._arrays().values():
        if slot.varies == "row":
            slot._data.array = slot._data.array[:0]
    empty._row_count = 0
    before = digest(path)
    assert lib.append(empty, path) == 0
    assert digest(path) == before


def test_a_widened_id_keeps_the_default_chunk(tmp_path):
    """40,000 short ids take one chunk of 40,000; a 24-byte id makes the
    dataset wider, and its chunk shrinks to the default for the new
    width, so the grown file draws no W12."""
    def store(ids):
        ds = lib.Dataset(writer="store", created="2026-10-16T00:00:00Z")
        ds.add_label("run", np.array(ids), "id")
        ds.add_scalar("cl", np.zeros(len(ids)), "1")
        return ds

    path = str(tmp_path / "ids.mes")
    lib.write(store(["r%05d" % i for i in range(40000)]), path)
    with h5py.File(path, "r") as f:
        assert f["run"].chunks == (40000,)
    assert lib.append(store(["a-much-longer-identifier"]), path) == 1
    with h5py.File(path, "r") as f:
        assert f["run"].dtype.itemsize == 24
        assert f["run"].chunks == (10922,)
        assert f["run"].shape == (40001,)
    report = lib.validate(path)
    assert report.errors == [] and "W12" not in report.warning_ids

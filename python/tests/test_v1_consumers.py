"""What TopoLink and romlib need, on the pinned surface, working.

Each operation is the right-hand column of the interface's table of
changes for today's consumers, plus the calls the two tools make
around them. For each, the names it uses must be on the pinned
surface (docs/surface/python.json) and the call must work on a real
file. A consumer that needed a name the surface does not list would
fail here, in this package's own suite.
"""

from __future__ import annotations

import json
import os

import numpy as np
import pytest

from tests import surface
from tests.v1_cases import CASES, QUAD_XY, lib


@pytest.fixture(scope="module")
def pinned():
    return json.loads(surface.SURFACE.read_text(encoding="utf-8"))["names"]


@pytest.fixture
def family(tmp_path):
    path = str(tmp_path / "family.mes")
    lib.write(CASES["family"](), path)
    return path


def on_surface(pinned, dotted):
    head, _, member = dotted.partition(".")
    assert head in pinned, "%s is not public" % head
    if member:
        assert member in pinned[head].get("members", {}), (
            "%s is not on the surface" % dotted)


# --------------------------------------------------------- TopoLink

def topolink_member_names(path, tmp):
    return list(lib.read(path).labels["run"].names().values)


def topolink_one_row_of_a_field(path, tmp):
    with lib.read(path) as ds:
        row = ds.mesh.node_arrays["pressure"].read(rows=slice(2, 3))
        coordinates = ds.mesh.coordinates.read(rows=slice(2, 3))
    assert row.dims == ("row", "node", "component")
    return row.shape, coordinates.shape


def topolink_builds_an_id_label(path, tmp):
    ds = lib.Dataset(writer="TopoLink 2.1", created="2026-10-16T00:00:00Z")
    ds.add_label("member", ["capsule_0000", "capsule_0001"], "id")
    ds.notes["producer"] = "TopoLink"
    ds.notes["parameters_sha256"] = "0" * 64
    ds.title = "capsule family"
    out = os.path.join(tmp, "ids.mes")
    lib.write(ds, out)
    return list(lib.read(out).labels["member"].names().values)


def topolink_appends_a_row(path, tmp):
    one = CASES["family"]()
    # The same family, its last run computed again: one row, replaced.
    with lib.read(path) as ds:
        rows = ds.row_count
    written = lib.append(_last_row(one), path, replace_by="run")
    with lib.read(path) as ds:
        assert ds.row_count == rows
    return written


def _last_row(full):
    ds = lib.Dataset(writer="TopoLink 2.1", created="2026-10-16T00:00:00Z")
    ds.add_parameter("mach", [0.8], "condition", "1", lower=0.5, upper=0.8)
    ds.add_label("member", [0], "group", categories=["m_c"])
    ds.set_generalisation_group("member")
    ds.add_label("status", [0], "status", categories=["converged"])
    ds.add_label("run", ["c-2"], "id")
    ds.add_label("split", [0], "split", categories=["test"])
    ds.add_scalar("cl", [0.32], "1")
    mesh = ds.set_mesh(full.mesh.cells(),
                       coordinates=(QUAD_XY * 1.2)[None], units="m",
                       dims=("group:member", "node", "component"))
    mesh.add_node_array("face", [1, 1, 2, 1, 1, 2], None, ("node",),
                        role="label")
    mesh.add_cell_array("face", [1, 2], None, ("cell",), role="label")
    ds.add_category_table("flag", ["ok"])
    mesh.add_cell_array("flagged", [[0, 0]], None, ("row", "cell"),
                        role="label", category="flag")
    mesh.add_node_array("pressure", np.full((1, 6), 1.0), "Pa",
                        ("row", "node"))
    mesh.add_cell_array("velocity", np.zeros((1, 2, 3)), "m s-1",
                        ("row", "cell", "component"))
    return ds


def topolink_checks_foreign_content(path, tmp):
    import h5py
    with h5py.File(path, "r+") as f:
        f.create_group("legacy_profile")
    return [(x.rule, x.path) for x in lib.validate(path).warnings
            if x.rule == "W11"]


def topolink_compacts(path, tmp):
    out = os.path.join(tmp, "compact.mes")
    with lib.read(path) as ds:
        lib.write(ds, out)
    return lib.validate(out).errors


# ------------------------------------------------------------ romlib

def romlib_input_table(path, tmp):
    with lib.read(path) as ds:
        table = lib.input_table(ds)
        names = [n for n, p in ds.parameters.items()
                 if p.role in ("design", "condition")]
    assert sorted(table) == sorted(names)
    return table.row_count


def romlib_writes_a_model(path, tmp):
    ds = lib.Dataset(writer="romlib 0.4", created="2026-10-16T00:00:00Z")
    ds.add_parameter("AoA", [], "condition", "degree", lower=-12.0,
                     upper=17.0)
    model = lib.Affine(["AoA"], {"CLtot": {"A": [[0.1]], "b": [0.0],
                                           "shape": []}})
    ds.add_callable("m1", model)
    ds.add_scalar("CLtot", None, "1", callable="m1", output="CLtot")
    mesh = ds.set_mesh(coordinates=np.zeros((3, 1)), units="m",
                       dims=("node", "component"))
    mesh.add_node_array("cp", None, "1", ("row", "node"), callable="m1",
                        output="cp")
    out = os.path.join(tmp, "model.mes")
    lib.write(ds, out)
    with lib.read(out) as back:
        assert back.mesh.node_arrays["cp"].served
    return out


def romlib_filters_by_role(path, tmp):
    with lib.read(path) as ds:
        conditions = [n for n, p in ds.parameters.items()
                      if p.role == "condition"]
        groups = [n for n, lab in ds.labels.items() if lab.role == "group"]
        served = [s.served for s in ds.scalars.values()]
        arrays = sorted(ds.mesh.node_arrays) + sorted(ds.mesh.cell_arrays)
    return conditions, groups, served, arrays


def romlib_registers_and_evaluates(path, tmp):
    class Served(lib.Callable):
        type = "composed-surrogate-test"

        def __call__(self, table):
            x = np.asarray(table["mach"].values, dtype=float)
            if x.size and x.max() > 10:
                raise lib.MestraError("", "out of range", "callables/m1")
            return {"cl": lib.Prediction(x * 2.0, np.full(x.shape, 0.1),
                                         level=0.95, method="test band")}

        def to_dict(self):
            return {"settings": {"n_draws": 2}}

        @classmethod
        def from_dict(cls, d):
            return cls()

    lib.register_callable(Served)
    assert lib.callable_types()["composed-surrogate-test"] is Served
    ds = lib.Dataset(writer="romlib 0.4", created="2026-10-16T00:00:00Z")
    ds.add_parameter("mach", [], "condition", "1", lower=0.1, upper=0.9)
    ds.add_callable("m1", Served())
    ds.add_scalar("cl", None, "1", callable="m1")
    ds.add_scalar("cl_band", None, "1", statistic="band", of="cl",
                  callable="m1", output="cl")
    out = os.path.join(tmp, "served.mes")
    lib.write(ds, out)
    with lib.read(out) as back:
        assert isinstance(back.callables["m1"], Served)
        record = lib.prediction(back, "cl", {"mach": [0.5]})
        filled = lib.evaluate(back, {"mach": [0.5]})
    assert filled.scalars["cl_band"].level == 0.95
    return record.mean.tolist(), record.level


def romlib_constructs_an_error(path, tmp):
    error = lib.MestraError("E12", "a band needs a level", "scalars/cl")
    return error.rule, error.message, error.path


OPERATIONS = [
    ("member names from the id label", topolink_member_names,
     ["read", "Dataset.labels", "Label.names"]),
    ("one row of a field and of the coordinates",
     topolink_one_row_of_a_field,
     ["Dataset.mesh", "Mesh.node_arrays", "Mesh.coordinates", "Slot.read",
      "NamedArray.dims", "Dataset.close"]),
    ("an id label, notes and metadata", topolink_builds_an_id_label,
     ["Dataset", "Dataset.add_label", "Dataset.notes", "Dataset.title",
      "write"]),
    ("append with replace_by", topolink_appends_a_row,
     ["append", "Dataset.add_parameter", "Dataset.set_mesh",
      "Mesh.add_node_array", "Mesh.add_cell_array", "Mesh.cells",
      "Dataset.add_category_table", "Dataset.set_generalisation_group",
      "Dataset.add_scalar", "Dataset.row_count"]),
    ("foreign content as W11 findings", topolink_checks_foreign_content,
     ["validate", "Report.warnings", "Finding.rule", "Finding.path"]),
    ("a rewrite that compacts", topolink_compacts, ["read", "write",
                                                    "Report.errors"]),
    ("the input table", romlib_input_table,
     ["input_table", "Dataset.parameters", "Parameter.role"]),
    ("served slots and served mesh arrays", romlib_writes_a_model,
     ["Dataset.add_callable", "Dataset.add_scalar", "Mesh.add_node_array",
      "Affine"]),
    ("filtering by role, served, arrays by location",
     romlib_filters_by_role,
     ["Dataset.parameters", "Dataset.labels", "Label.role", "Slot.served",
      "Mesh.node_arrays", "Mesh.cell_arrays", "Dataset.scalars"]),
    ("a registered type, predictions and evaluation",
     romlib_registers_and_evaluates,
     ["Callable", "register_callable", "callable_types", "Prediction",
      "prediction", "evaluate", "Dataset.callables", "Slot.level"]),
    ("the error constructor", romlib_constructs_an_error,
     ["MestraError", "MestraError.rule", "MestraError.message",
      "MestraError.path"]),
]


@pytest.mark.parametrize("what, call, names", OPERATIONS,
                         ids=[o[0] for o in OPERATIONS])
def test_each_consumer_operation_is_public_and_works(pinned, family,
                                                     tmp_path, what, call,
                                                     names):
    for name in names:
        on_surface(pinned, name)
    result = call(family, str(tmp_path))
    assert result is not None, what


def test_the_results_are_what_the_consumers_expect(family, tmp_path):
    tmp = str(tmp_path)
    assert topolink_member_names(family, tmp)[:2] == ["a-1", "a-2"]
    assert topolink_one_row_of_a_field(family, tmp) == ((1, 6, 1),
                                                        (1, 6, 3))
    assert topolink_builds_an_id_label(family, tmp) == ["capsule_0000",
                                                        "capsule_0001"]
    assert topolink_appends_a_row(family, tmp) == 1
    assert topolink_checks_foreign_content(family, tmp) == [
        ("W11", "legacy_profile")]
    assert topolink_compacts(family, tmp) == []
    assert romlib_input_table(family, tmp) == 6
    assert romlib_registers_and_evaluates(family, tmp) == ([1.0], 0.95)
    assert romlib_constructs_an_error(family, tmp) == (
        "E12", "a band needs a level", "scalars/cl")

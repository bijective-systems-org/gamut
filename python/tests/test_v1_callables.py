"""Callables on version 1 slots: inputs, the input table, evaluation
and predictions.

`inputs` is a set, compared with the dictionary's own columns only when
it is declared; without it a callable gets every design, condition and
time parameter, as in version 0. The input table maps names to arrays
with a leading row axis, fields included. Derivatives are ordinary
outputs. The built-in affine runs through all of it.
"""

from __future__ import annotations

import numpy as np
import pytest

from tests.v1_cases import CASES, QUAD_XY, lib, model_affine

pytestmark = pytest.mark.filterwarnings("error")


@pytest.fixture
def model_file(tmp_path):
    path = str(tmp_path / "model.mes")
    lib.write(CASES["model"](), path)
    return path


# ------------------------------------------------- the worked example

def test_affine_evaluates_the_worked_example(model_file, tmp_path):
    with lib.read(model_file) as ds:
        out = lib.evaluate(ds, {"mach": [0.5], "alpha": [4.0]})
    assert out.row_count == 1
    assert out.scalars["cl"].read().values.tolist() == [1.45]
    assert out.scalars["cl_band"].read().values.tolist() == [0.02]
    assert (out.scalars["cl_band"].level, out.scalars["cl_band"].method) \
        == (0.95, "constant band")
    pressure = out.mesh.node_arrays["pressure"].read().values[0, :, 0]
    np.testing.assert_array_equal(pressure, [0.5, 1.1, 3.7, 4.3, 6.9, 7.5])
    band = out.mesh.node_arrays["pressure_band"]
    assert band.level == 0.68
    np.testing.assert_array_equal(band.read().values[0, :, 0],
                                  [0.05, 0.10, 0.15, 0.20, 0.25, 0.30])
    assert not out.callables and all(not s.served
                                     for s in out._slots().values())
    path = str(tmp_path / "evaluated.mes")
    lib.write(out, path)
    report = lib.validate(path)
    assert report.errors == []
    with lib.read(path) as back:
        assert "callables" not in back._present
        assert back.scalars["cl"].read().values.tolist() == [1.45]


def test_prediction_of_a_served_slot(model_file):
    with lib.read(model_file) as ds:
        record = lib.prediction(ds, "cl", {"mach": [0.5, 0.1],
                                           "alpha": [4.0, 0.0]})
        field = lib.prediction(ds, "node_arrays/pressure",
                               {"mach": [0.5], "alpha": [4.0]})
        with pytest.raises(lib.MestraError):
            lib.prediction(ds, "cl_band", {"mach": [0.5], "alpha": [4.0]})
    np.testing.assert_array_equal(record.mean, [1.45, 0.25])
    assert record.level == 0.95
    assert field.mean.shape == (1, 6, 1)


def test_prediction_of_a_stored_slot_finds_its_band(tmp_path):
    ds = CASES["family"]()
    ds.mesh.add_node_array("pressure_band", np.full((6, 6), 3.0), "Pa",
                           ("row", "node"), statistic="band",
                           of="pressure", level=0.9, method="spread")
    record = lib.prediction(ds, "pressure")
    assert record.mean.shape == (6, 6, 1)
    assert record.level == 0.9 and float(record.uncertainty[0, 0, 0]) == 3.0
    with pytest.raises(lib.MestraError):
        lib.prediction(ds, "pressure", {"mach": [0.5]})


def test_a_name_shared_by_node_and_cell_arrays_must_be_qualified():
    ds = CASES["family"]()
    with pytest.raises(lib.MestraError) as caught:
        lib.prediction(ds, "face")
    assert "node_arrays/face" in caught.value.message
    assert lib.prediction(ds, "cell_arrays/face").mean.shape == (6, 2, 1)


# ------------------------------------------------------------- inputs

def model(inputs, keys=("mach", "alpha")):
    ds = lib.Dataset(created="2026-10-16T00:00:00Z")
    ds.add_parameter("mach", [0.5, 0.6], "condition", "1", lower=0.3,
                     upper=0.9)
    ds.add_parameter("alpha", [4.0, 2.0], "condition", "degree", lower=0.0,
                     upper=8.0)
    ds.add_parameter("beta", [0.0, 1.0], "condition", "degree", lower=-2.0,
                     upper=2.0)
    m = lib.Affine(list(keys), {"cl": {"A": [[1.0] * len(keys)],
                                       "b": [0.0], "shape": []}})
    ds.add_callable("m1", m, inputs=inputs)
    ds.add_scalar("cl", None, "1", callable="m1")
    return ds


def test_inputs_are_a_set():
    one = lib.evaluate(model(["alpha", "mach"]))
    two = lib.evaluate(model(["mach", "alpha"]))
    np.testing.assert_array_equal(one.scalars["cl"].read().values,
                                  two.scalars["cl"].read().values)
    np.testing.assert_array_equal(one.scalars["cl"].read().values,
                                  [4.5, 2.6])


def test_inputs_and_the_dictionary_columns_must_be_equal_when_declared():
    with pytest.raises(lib.MestraError) as caught:
        lib.evaluate(model(["mach"]))
    assert "must be equal" in caught.value.message
    with pytest.raises(lib.MestraError):
        lib.evaluate(model(["mach", "alpha", "beta"]))


def test_without_inputs_the_callable_gets_every_parameter():
    seen = {}

    class Spy(lib.Callable):
        type = "spy"

        def __call__(self, table):
            seen["names"] = sorted(table)
            seen["rows"] = table.row_count
            return {"cl": lib.Prediction(np.zeros(table.row_count))}

        def to_dict(self):
            return {}

        @classmethod
        def from_dict(cls, d):
            return cls()

    ds = model(None)
    ds.callables["m1"] = Spy()
    lib.evaluate(ds)
    assert seen == {"names": ["alpha", "beta", "mach"], "rows": 2}


def test_inputs_are_written_and_read_back(tmp_path):
    path = str(tmp_path / "m.mes")
    lib.write(model(["mach", "alpha"]), path)
    with lib.read(path) as ds:
        assert ds._callable_inputs["m1"] == frozenset(["mach", "alpha"])
        assert ds.callables["m1"].inputs == frozenset(["mach", "alpha"])
        np.testing.assert_array_equal(
            lib.evaluate(ds).scalars["cl"].read().values, [4.5, 2.6])
        again = str(tmp_path / "again.mes")
        lib.write(ds, again)
    with lib.read(again) as ds:
        assert ds._callable_inputs["m1"] == frozenset(["mach", "alpha"])


def test_an_inputs_entry_must_be_a_name():
    with pytest.raises(lib.MestraError) as caught:
        model(["mach alpha"])
    assert caught.value.rule == "E45"
    with pytest.raises(lib.MestraError):
        model("mach alpha")


# --------------------------------------------------------- the table

def test_the_input_table_of_a_dataset_has_a_leading_row_axis():
    ds = CASES["family"]()
    table = lib.input_table(ds, ["mach", "cl", "node_arrays/pressure",
                                 "cell_arrays/velocity"])
    assert table.row_count == 6
    assert table["mach"].dims == ("row",)
    assert table["cl"].dims == ("row",)
    assert table["node_arrays/pressure"].dims == ("row", "node",
                                                  "component")
    assert table["cell_arrays/velocity"].values.shape == (6, 2, 3)
    default = lib.input_table(ds)
    assert sorted(default) == ["mach"]
    with pytest.raises(lib.MestraError) as caught:
        lib.input_table(ds, ["nothing"])
    assert caught.value.rule == "E45"


def test_the_input_table_of_a_mapping():
    table = lib.input_table({"mach": [0.5, 0.6],
                             "node_arrays/p": np.zeros((2, 3, 1))})
    assert table.row_count == 2
    assert table["node_arrays/p"].dims == ("row", "node", "component")
    with pytest.raises(lib.MestraError):
        lib.input_table({"a": [1.0], "b": [1.0, 2.0]})
    pairs = lib.input_table(np.array([[1.0, 2.0], [3.0, 4.0]]),
                            ["mach", "alpha"])
    assert pairs["alpha"].values.tolist() == [2.0, 4.0]


def test_a_callable_may_read_a_field():
    class Mean(lib.Callable):
        type = "mean-of-field"

        def __call__(self, table):
            field = table["node_arrays/pressure"].values
            return {"p_mean": lib.Prediction(field.mean(axis=(1, 2)))}

        def to_dict(self):
            return {}

        @classmethod
        def from_dict(cls, d):
            return cls()

    ds = CASES["family"]()
    ds.add_callable("mf", Mean(), inputs=["node_arrays/pressure"])
    ds.add_scalar("p_mean", None, "Pa", callable="mf")
    out = lib.evaluate(ds)
    expect = (np.arange(36.0).reshape(6, 6) * 10.0).mean(axis=1)
    np.testing.assert_allclose(out.scalars["p_mean"].read().values, expect)


# ------------------------------------------------- derivatives, dtypes

def test_a_derivative_is_an_ordinary_output(tmp_path):
    ds = lib.Dataset(created="2026-10-16T00:00:00Z")
    ds.add_parameter("mach", [], "condition", "1", lower=0.3, upper=0.9)
    ds.add_parameter("alpha", [], "condition", "degree", lower=0.0,
                     upper=8.0)
    m = lib.Affine(["mach", "alpha"],
                   {"cl": {"A": [[2.0, 0.1]], "b": [0.05], "shape": []},
                    "dcl_dmach": {"A": [[0.0, 0.0]], "b": [2.0],
                                  "shape": []}})
    ds.add_callable("m1", m, inputs=["mach", "alpha"])
    ds.add_scalar("cl", None, "1", callable="m1")
    ds.add_scalar("dcl_dmach", None, "1", of="cl", with_respect_to="mach",
                  callable="m1", output="dcl_dmach")
    path = str(tmp_path / "grad.mes")
    lib.write(ds, path)
    with lib.read(path) as back:
        assert back.addons == ["gradients", "model"]
        slot = back.scalars["dcl_dmach"]
        assert (slot.of, slot.with_respect_to, slot.output) == (
            "cl", "mach", "dcl_dmach")
        out = lib.evaluate(back, {"mach": [0.5], "alpha": [4.0]})
    assert out.scalars["dcl_dmach"].read().values.tolist() == [2.0]
    assert out.scalars["dcl_dmach"].with_respect_to == "mach"


def test_evaluation_writes_float64_and_refuses_a_dtype_on_served_slots():
    ds = model(["mach", "alpha"])
    out = lib.evaluate(ds)
    assert out.scalars["cl"].dtype == np.dtype("<f8")
    with pytest.raises(lib.MestraError):
        ds.add_scalar("cl32", None, "1", callable="m1", output="cl",
                      dtype="float32")


def test_a_band_slot_whose_output_has_no_band_is_refused():
    ds = model(["mach", "alpha"])
    ds.add_scalar("cl_band", None, "1", statistic="band", of="cl",
                  callable="m1", output="cl")
    with pytest.raises(lib.MestraError) as caught:
        lib.evaluate(ds)
    assert caught.value.rule == "E12"


def test_an_unregistered_type_is_copied_and_refused_on_evaluation(
        tmp_path, model_file):
    import h5py
    with h5py.File(model_file, "r+") as f:
        from mestra.encoding import write_string_attr
        write_string_attr(f["callables/m1"], "type", "nobody")
    with lib.read(model_file) as ds:
        opaque = ds.callables["m1"]
        assert isinstance(opaque, lib.OpaqueCallable)
        assert opaque.type == "nobody"
        assert opaque.inputs == frozenset(["mach", "alpha"])
        with pytest.raises(lib.MestraError):
            lib.evaluate(ds, {"mach": [0.5], "alpha": [4.0]})
        again = str(tmp_path / "copy.mes")
        lib.write(ds, again)
    with lib.read(again) as ds:
        assert ds.callables["m1"].to_dict()["keys"] == ["mach", "alpha"]


def test_a_served_mesh_s_coordinates(tmp_path):
    ds = lib.Dataset(created="2026-10-16T00:00:00Z")
    ds.add_parameter("scale", [], "design", "1", lower=1.0, upper=2.0)
    flat = QUAD_XY.reshape(-1)
    geometry = lib.Affine(["scale"], {"coordinates": {
        "A": flat.reshape(-1, 1), "b": np.zeros(flat.size),
        "shape": [6, 3]}})
    ds.add_callable("g", geometry, inputs=["scale"])
    from tests.v1_cases import QUAD_CONNECTIVITY, QUAD_OFFSETS, QUAD_TYPES
    ds.set_mesh((QUAD_TYPES, QUAD_OFFSETS, QUAD_CONNECTIVITY), units="m",
                dims=("row", "node", "component"), n_nodes=6,
                callable="g", output="coordinates", components=3)
    path = str(tmp_path / "geometry.mes")
    lib.write(ds, path)
    with lib.read(path) as back:
        assert back.mesh.coordinates.served
        out = lib.evaluate(back, {"scale": [2.0]})
    np.testing.assert_array_equal(
        out.mesh.coordinates.read().values[0], QUAD_XY * 2.0)


def test_model_affine_round_trips_through_its_dictionary():
    m = model_affine()
    again = lib.Affine.from_dict(m.to_dict())
    record = again({"mach": [0.5], "alpha": [4.0]})
    assert record["cl"].mean.tolist() == [1.45]

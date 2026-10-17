"""Evaluating a file's callables, and writing the result out."""

from __future__ import annotations

import numpy as np
import pytest

from mestra import _v0 as mestra
from mestra.errors import MestraError
from tests import corpus


def test_distillation_gives_a_plain_data_file(tmp_path):
    """Section 10: the same slots, now holding data.

    docs/example.md: writing those out turns the callable file into
    one like file one, with source = data everywhere, the same
    support_id and one row.
    """
    with mestra.read(corpus.case_path("affine_zero_rows")) as ds:
        out = mestra.evaluate(ds, {"mach": [0.5], "alpha": [4.0]})
    assert out.n_rows == 1
    assert out.callables == {}
    assert out.scalars["cl"].source == "data"
    assert out.supports["s0"].support_id == \
        "96df395d80ef548444562292de441525ba0b5c8ad00a8dadff19a19c943936c7"
    pressure = out.supports["s0"].node_arrays["pressure"]
    assert pressure.source == "data"
    assert pressure.read().shape == (1, 6, 1)
    assert pressure.read().at(row=0, node=2, component=0) == 3.7

    path = str(tmp_path / "distilled.mes")
    mestra.write(out, path)
    report = mestra.validate(path)
    assert report.error_ids == []
    assert report.warning_ids == []
    with mestra.read(path) as back:
        assert back.n_rows == 1
        assert back.scalars["cl"].read().at(row=0) == 1.45
        assert back.supports["s0"].node_arrays["pressure"].dims == (
            "row", "node", "component")


def test_a_grid_of_keys():
    with mestra.read(corpus.case_path("callable_two_slots")) as ds:
        mach = np.linspace(0.1, 0.9, 9)
        out = mestra.evaluate(ds, {"mach": mach})
    assert out.n_rows == 9
    heat = out.supports["s0"].node_arrays["heat_flux"].read()
    assert heat.shape == (9, 6, 1)
    assert heat.at(row=0, node=0, component=0) == pytest.approx(2.0)


def test_a_two_dimensional_table():
    with mestra.read(corpus.case_path("affine_zero_rows")) as ds:
        table = np.array([[4.0, 0.5], [6.0, 0.6]])
        out = mestra.evaluate(ds, table, ["alpha", "mach"])
    assert out.n_rows == 2
    assert out.keys["mach"].read().values.tolist() == [0.5, 0.6]


def test_a_missing_column_names_the_key():
    with mestra.read(corpus.case_path("affine_zero_rows")) as ds, \
            pytest.raises(MestraError) as caught:
        mestra.evaluate(ds, {"mach": [0.5]})
    assert "alpha" in str(caught.value)


def test_a_file_with_rows_and_callables_evaluates(tmp_path):
    """Section 22: the row count decides nothing."""
    with mestra.read(corpus.case_path("affine_with_rows")) as ds:
        out = mestra.evaluate(ds, {"mach": [0.1, 0.9],
                                   "alpha": [-2.0, 10.0]})
        one = mestra.evaluate(ds, {"mach": [0.5], "alpha": [4.0]})
    assert out.n_rows == 2
    assert one.n_rows == 1
    assert out.scalars["cl"].read().at(row=1) == pytest.approx(2.85)


def test_stored_rows_must_match_the_table():
    """Stored row-varying data cannot be stretched to fit a table."""
    ds = mestra.Dataset(writer="t")
    ds.add_key("mach", [0.4, 0.8], role="condition", units="1")
    ds.add_scalar("cd", [0.01, 0.02], units="1")
    ds.add_callable("m1", mestra.Affine(
        ["mach"], {"cl": {"A": [[2.0]], "b": [0.05], "shape": []}}))
    ds.add_scalar("cl", callable_id="m1", output="cl", units="1")
    assert mestra.evaluate(ds, {"mach": [0.4, 0.8]}).n_rows == 2
    with pytest.raises(MestraError) as caught:
        mestra.evaluate(ds, {"mach": [0.5]})
    assert caught.value.rule == "E16"


def test_the_keys_keep_their_roles_and_bounds():
    with mestra.read(corpus.case_path("affine_zero_rows")) as ds:
        out = mestra.evaluate(ds, {"mach": [0.5], "alpha": [4.0]})
    assert out.keys["mach"].role == "condition"
    assert (out.keys["mach"].lower, out.keys["mach"].upper) == (0.1, 0.9)
    assert out.keys["alpha"].units == "degree"


def test_a_band_slot_takes_the_uncertainty_and_its_level(tmp_path):
    """Section 10: which part of the record fills a slot is its
    statistic, and evaluation writes level and method on the band."""
    with mestra.read(corpus.case_path("affine_band")) as ds:
        out = mestra.evaluate(ds, {"mach": [0.1, 0.9],
                                   "alpha": [-2.0, 10.0]})
    band = out.scalars["cl_band"]
    assert band.source == "data" and band.statistic == "band"
    assert band.of == "cl" and band.level == 0.95
    assert band.method == "constant band"
    assert band.read().values.tolist() == [0.02, 0.02]
    pressure_band = out.supports["s0"].node_arrays["pressure_band"]
    assert pressure_band.level == 0.68
    assert pressure_band.read().at(row=1, node=5, component=0) == 0.30
    assert out.scalars["cl"].level is None
    path = str(tmp_path / "banded.mes")
    mestra.write(out, path)
    report = mestra.validate(path)
    assert report.error_ids == [] and report.warning_ids == []
    with mestra.read(path) as back:
        assert back.scalars["cl_band"].level == 0.95
        assert back.scalars["cl_band"].method == "constant band"


def test_a_band_slot_needs_a_record_with_a_band():
    """A band slot served by an output that has no uncertainty cannot
    be filled: the file would hold a band with no level."""
    ds = mestra.Dataset(writer="t")
    ds.add_key("mach", [], role="condition", units="1", lower=0.1,
               upper=0.9)
    ds.add_callable("m1", mestra.Affine(
        ["mach"], {"cl": {"A": [[2.0]], "b": [0.05], "shape": []}}))
    ds.add_callable_slot("cl", units="1", callable="m1")
    ds.add_callable_slot("cl_band", units="1", callable="m1", output="cl",
                         statistic="band", of="cl")
    with pytest.raises(MestraError) as caught:
        mestra.evaluate(ds, {"mach": [0.5]})
    assert caught.value.rule == "E12"
    assert "cl_band" in str(caught.value)


@pytest.mark.parametrize("name", ["affine_zero_rows",
                                  "affine_with_rows",
                                  "callable_two_slots",
                                  "affine_band"])
def test_an_evaluated_file_has_no_callables_group_at_all(tmp_path, name):
    """Section 7 of docs/api-conventions.md.

    "Evaluating a file turns every callable slot into a stored slot,
    so the result has no callable to keep: the `/callables` group is
    absent from an evaluated file, not present and empty."

    That sentence has been read three ways, one of them a group
    present and empty. The difference is invisible in the values and
    visible under section 30's structural equality, so it is asserted
    on the file and not on the dataset.
    """
    import h5py

    source = corpus.case_path(name)
    entries = corpus.expected(name)["evaluation"]
    table = {key: np.array([corpus.as_float(v) for v in values])
             for key, values in entries[0]["keys"].items()}
    written = str(tmp_path / "evaluated.mes")
    with mestra.read(source) as ds:
        out = mestra.evaluate(ds, table)
    mestra.write(out, written)

    assert out.callables == {}
    with h5py.File(source, "r") as f:
        assert "callables" in f          # the case has one to lose
    with h5py.File(written, "r") as f:
        assert "callables" not in f
    for slot in out.slots().values():
        assert slot.source == "data", slot.name
    assert mestra.validate(written).errors == []

"""Reading: what the file says, what it does not, and what it keeps."""

from __future__ import annotations

import h5py
import numpy as np
import pytest

from mestra import _v0 as mestra
from mestra.errors import MestraError
from tests import corpus


def test_the_version_is_refused_outright():
    """Section 28: a reader of mestra/0 refuses any other major."""
    with pytest.raises(MestraError) as caught:
        mestra.read(corpus.case_path("err_e01"))
    assert caught.value.rule == "E01"


def test_what_a_reader_reports_without_reading_an_array():
    with mestra.read(corpus.case_path("mesh_two_rows")) as ds:
        assert ds.n_rows == 2
        assert ds.aligned is True
        assert ds.generalisation_group == "member"
        assert ds.key_names() == ["mach", "member"]
        assert ds.keys["mach"].role == "condition"
        assert (ds.keys["mach"].lower, ds.keys["mach"].upper) == (0.1,
                                                                  0.9)
        assert ds.supports["s0"].stored_support_id.startswith("96df")
        assert ds.supports["s0"].n_nodes == 6
        slot = ds.supports["s0"].node_arrays["pressure"]
        assert (slot.role, slot.varies, slot.units) == ("field", "row",
                                                        "Pa")
        assert slot.components == 1
        assert slot.source == "data"


def test_dimension_names_come_from_the_link_and_not_from_NAME():
    """Section 21: NAME says the same sentence in every file."""
    with mestra.read(corpus.case_path("mesh_two_rows")) as ds:
        assert ds.supports["s0"].node_arrays["pressure"].dims == (
            "row", "node", "component")
        assert ds.supports["s0"].coordinates.dims == (
            "group:member", "node", "component")
    with h5py.File(corpus.case_path("mesh_two_rows"), "r") as f:
        name = f["row"].attrs["NAME"]
        assert b"netCDF dimension" in name


def test_the_group_instance_is_the_category_id():
    """Section 21: instance i is the category with id i."""
    with mestra.read(corpus.case_path("mesh_two_rows")) as ds:
        member = np.asarray(ds.keys["member"].values)
        coordinates = ds.supports["s0"].coordinates.values
        for row in range(ds.n_rows):
            instance = int(member[row])
            assert coordinates.at(instance=instance, node=2,
                                  component=0) == (2.0, 3.0)[row]


def test_a_row_varying_array_in_an_unaligned_file():
    """Section 22: the leading index is a position on the support."""
    name = "two_supports_row_varying"
    with mestra.read(corpus.case_path(name)) as ds:
        assert ds.aligned is False
        assert list(ds.row_support) == [0, 1, 0]
        assert list(ds.rows_on("s0")) == [0, 2]
        assert ds.support_of_row(1).name == "s1"
        pressure = ds.supports["s0"].node_arrays["pressure"].values
        assert pressure.at(row=1, node=2, component=0) == 302.0


def test_a_string_id_column():
    with mestra.read(corpus.case_path("cascade_varying_geometry")) as ds:
        identifiers = ds.keys["id"].values
        assert list(identifiers) == ["s000", "s001", "s002", "s003"]


def test_a_label_without_a_category_table():
    with mestra.read(corpus.case_path("labels_tables")) as ds:
        faces = ds.supports["s0"].node_arrays["cad_face_id"]
        assert faces.category is None
        assert faces.values.at(node=5, component=0) == 23
        region = ds.supports["s0"].cell_arrays["region"]
        assert ds.categories[region.category][1] == "outlet"


def test_draws_and_their_summaries():
    with mestra.read(corpus.case_path("draws_and_summaries")) as ds:
        draws = ds.supports["s0"].node_arrays["pressure"]
        assert draws.statistic == "draw"
        assert draws.of is None
        assert draws.dims == ("row", "draw", "node", "component")
        assert draws.values.at(row=1, draw=2, node=4,
                               component=0) == 234.0
        q90 = ds.supports["s0"].node_arrays["pressure_q90"]
        assert (q90.statistic, q90.of, q90.quantile) == ("quantile",
                                                         "pressure", 0.9)


def test_notes_and_unknown_things_survive_a_rewrite(tmp_path):
    """Section 28: ignore it, report it, do not lose it."""
    source = corpus.case_path("warn_w11")
    path = str(tmp_path / "again.mes")
    with mestra.read(source) as ds:
        assert "comment" in ds.extra
        assert "extras" in ds.opaque
        mestra.write(ds, path)
    assert corpus.structural_diff(source, path) == []
    assert mestra.validate(path).warning_ids == ["W11"]


def test_a_private_group_is_copied_and_not_interpreted(tmp_path):
    """The case is E18, so writing it back needs `check=False`."""
    source = corpus.case_path("err_e18")
    path = str(tmp_path / "again.mes")
    with mestra.read(source) as ds:
        assert "private" in ds.opaque
        assert ds.generalisation_group is None
        mestra.write(ds, path, check=False)
    with h5py.File(path, "r") as f:
        assert "private" in f


def test_notes_round_trip(tmp_path):
    ds = mestra.Dataset(writer="t",
                        notes={"solver": "an open one", "runs": 12})
    ds.add_key("mach", [0.4], role="condition", units="1")
    path = str(tmp_path / "notes.mes")
    mestra.write(ds, path)
    assert mestra.validate(path).error_ids == []
    with mestra.read(path) as back:
        assert back.notes == {"solver": "an open one", "runs": 12}


def test_to_xarray():
    xr = pytest.importorskip("xarray")
    with mestra.read(corpus.case_path("mesh_two_rows"),
                     lazy=False) as ds:
        converted = ds.to_xarray()
    assert isinstance(converted, xr.Dataset)
    assert converted["pressure"].dims == ("row", "node", "component_1")
    assert float(converted["pressure"][1, 3, 0]) == 204.0
    assert converted["coordinates"].dims == ("group_member", "node",
                                             "component_2")
    assert converted["mach"].attrs["role"] == "condition"
    assert converted.attrs["format"] == "mestra/0"


def test_what_a_reader_must_not_judge(tmp_path):
    """Sections 12, 28 and 29: opaque means opaque.

    A producer may keep its own records under /private in whatever
    representation it chooses, and a version may add a group this
    reader does not know. Neither is validated, both survive a
    rewrite, and the unknown group is reported.
    """
    import shutil
    path = str(tmp_path / "opaque.mes")
    shutil.copy(corpus.case_path("mesh_two_rows"), path)
    with h5py.File(path, "a") as f:
        private = f.create_group("private")
        private.attrs.create("note", "anything at all")
        private.create_dataset("fitted_state",
                               data=np.zeros((3, 3), dtype="float32"))
        f.create_group("extras").create_dataset(
            "whatever", data=np.arange(4, dtype="uint16"))
    report = mestra.validate(path)
    assert report.error_ids == []
    assert report.warning_ids == ["W11"]
    again = str(tmp_path / "again.mes")
    with mestra.read(path) as ds:
        mestra.write(ds, again)
    assert corpus.structural_diff(path, again) == []

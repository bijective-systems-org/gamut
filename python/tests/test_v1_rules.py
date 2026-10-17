"""The rules of version 1, each drawn by one file changed by hand.

Every file here is one of the version 1 test files with one thing
changed in h5py, next to the rule it must draw and where. Each new or
changed rule (section 13 of the draft: E45, E47, E48, E49, W18, W19,
and the kept rules marked as changed) has a case that fires and a case
that stays silent; the silent case is usually the unchanged file.
"""

from __future__ import annotations

import shutil

import h5py
import numpy as np
import pytest

from mestra.encoding import (
    make_scale,
    write_float_attr,
    write_int_attr,
    write_string_attr,
)
from tests.v1_cases import lib, write_case

pytestmark = pytest.mark.filterwarnings("error")


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    directory = tmp_path_factory.mktemp("rules")
    return {name: write_case(name, directory)
            for name in ("table", "family", "points", "model",
                         "transient", "relations")}


@pytest.fixture
def changed(base, tmp_path):
    """A copy of one base file, changed by `change(f)` in h5py."""
    def make(name, change):
        path = str(tmp_path / (name + ".mes"))
        shutil.copy(base[name], path)
        with h5py.File(path, "r+") as f:
            change(f)
        return path
    return make


def errors_at(report, rule):
    return sorted(f.path for f in report.errors if f.rule == rule)


def warnings_at(report, rule):
    return sorted(f.path for f in report.warnings if f.rule == rule)


def recreate(f, path, values=None, dtype=None, chunks="keep",
             maxshape="keep", dims=None, **extra):
    """Replace a dataset with the same attributes and dimension scales
    (or the scales at the paths `dims` names, one per axis) and
    different values, dtype, chunks or maximum shape."""
    old = f[path]
    attrs = {k: (old.attrs[k], old.attrs.get_id(k).get_type())
             for k in old.attrs if k not in ("DIMENSION_LIST",)}
    scales = [list(dim.values()) for dim in old.dims]
    data = old[()] if values is None else np.asarray(values)
    dtype = data.dtype if dtype is None else np.dtype(dtype)
    kw = {}
    kw["chunks"] = old.chunks if chunks == "keep" else chunks
    kw["maxshape"] = old.maxshape if maxshape == "keep" else maxshape
    if kw["chunks"] is None:
        kw.pop("chunks")
        kw.pop("maxshape")
    for axis, dim in enumerate(old.dims):
        for scale in list(dim.values()):
            old.dims[axis].detach_scale(scale)
    del f[path]
    new = f.create_dataset(path, data=data.astype(dtype), dtype=dtype,
                           track_times=False, **kw, **extra)
    for name, (value, htype) in attrs.items():
        if isinstance(htype, h5py.h5t.TypeStringID):
            space = h5py.h5s.create(h5py.h5s.SCALAR)
            attr = h5py.h5a.create(new.id, name.encode(), htype, space)
            attr.write(np.array(value, dtype="S%d" % htype.get_size()),
                       mtype=htype)
        else:
            new.attrs.create(name, value)
    if dims is not None:
        scales = [[f[d]] for d in dims]
    for axis, found in enumerate(scales):
        if axis < new.ndim:
            for scale in found:
                new.dims[axis].attach_scale(scale)
    return new


def test_every_base_file_is_clean(base):
    for name, path in base.items():
        report = lib.validate(path)
        assert report.errors == [], (name, report)
        expect = ["W02"] if name in ("family", "relations") else []
        assert report.warning_ids == expect, (name, report)


# ------------------------------------------------------------- E01

def test_e01_a_version_0_file_is_refused_naming_the_upgrade(changed):
    path = changed("table", lambda f: write_string_attr(
        f, "format", "mestra/0"))
    report = lib.validate(path)
    assert report.error_ids == ["E01"]
    assert "upgrade" in report.errors[0].message
    with pytest.raises(lib.MestraError) as caught:
        lib.read(path)
    assert caught.value.rule == "E01"
    assert "mestra.upgrade" in caught.value.message


def test_e01_another_major_version_is_refused(changed, base):
    path = changed("table", lambda f: write_string_attr(
        f, "format", "mestra/2"))
    assert lib.validate(path).error_ids == ["E01"]
    assert "E01" not in lib.validate(base["table"]).error_ids


# ------------------------------------------------------------- E02

def test_e02_an_unknown_role_on_a_mesh_array(changed):
    path = changed("family", lambda f: write_string_attr(
        f["mesh/node_arrays/pressure"], "role", "flux"))
    report = lib.validate(path)
    assert report.error_ids == ["E02"]
    assert errors_at(report, "E02") == ["mesh/node_arrays/pressure"]


def test_e02_an_unknown_statistic(changed):
    path = changed("points", lambda f: write_string_attr(
        f["mesh/node_arrays/dp_std"], "statistic", "quantile"))
    report = lib.validate(path)
    assert report.error_ids == ["E02"]
    assert errors_at(report, "E02") == ["mesh/node_arrays/dp_std"]


def test_e02_an_unknown_mesh_kind(changed, base):
    path = changed("points", lambda f: write_string_attr(
        f["mesh"], "kind", "axis"))
    report = lib.validate(path)
    assert report.error_ids == ["E02"]
    assert errors_at(report, "E02") == ["mesh"]
    assert "E02" not in lib.validate(base["points"]).error_ids


def test_e02_is_never_an_unknown_root_role(changed):
    """A root object with a role this reader does not know is W11 and
    ignored: later 1.x additions stay additive."""
    def change(f):
        extra = f.create_dataset("telemetry", data=np.arange(4.0),
                                 chunks=(4,), maxshape=(None,),
                                 track_times=False)
        extra.dims[0].attach_scale(f["row"])
        write_string_attr(extra, "role", "telemetry")
        write_string_attr(extra, "units", "furlongs per fortnight")
    path = changed("table", change)
    report = lib.validate(path)
    assert report.errors == []
    assert warnings_at(report, "W11") == ["telemetry"]
    with lib.read(path) as ds:                    # a strict read opens it
        assert "telemetry" not in ds.scalars
    again = path + ".again.mes"
    with lib.read(path) as ds:
        lib.write(ds, again)                      # and a rewrite keeps it
    with h5py.File(again, "r") as f:
        assert f["telemetry"].attrs["role"] == b"telemetry"
        np.testing.assert_array_equal(f["telemetry"][()], np.arange(4.0))


# ------------------------------------------------------------- E03

def test_e03_a_mesh_without_coordinates(changed, base):
    def change(f):
        del f["mesh/coordinates"]
    report = lib.validate(changed("model", change))
    assert report.error_ids == ["E03"]
    assert errors_at(report, "E03") == ["mesh"]
    assert "E03" not in lib.validate(base["model"]).error_ids


def test_e03_a_second_coordinates_array(changed):
    path = changed("family", lambda f: write_string_attr(
        f["mesh/node_arrays/pressure"], "role", "coordinates"))
    report = lib.validate(path)
    assert report.error_ids == ["E03"]
    assert errors_at(report, "E03") == ["mesh/node_arrays/pressure"]


def test_e03_two_status_labels(changed):
    path = changed("table", lambda f: write_string_attr(
        f["fidelity"], "role", "status"))
    report = lib.validate(path)
    assert report.error_ids == ["E03"]
    assert errors_at(report, "E03") == ["labels/status"]


def test_e03_two_id_labels(changed):
    def change(f):
        write_string_attr(f["n_ribs"], "role", "id")
        for name in ("units", "lower", "upper"):
            del f["n_ribs"].attrs[name]
    report = lib.validate(changed("table", change))
    assert report.error_ids == ["E03"]


def test_e03_points_coordinates_of_more_than_three_components(changed,
                                                              base):
    from mestra.encoding import support_digest

    def change(f):
        values = np.zeros((8, 4))
        values[:, 0] = np.linspace(0.0, 0.2, 8)
        make_scale(f, "component_4", 4)
        recreate(f, "mesh/coordinates", values=values, chunks=None)
        coordinates = f["mesh/coordinates"]
        coordinates.dims[1].detach_scale(f["component_1"])
        coordinates.dims[1].attach_scale(f["component_4"])
        write_int_attr(coordinates, "components", 4)
        write_string_attr(f["mesh"], "support_id",
                          support_digest(8, axis_coordinates=values))
    report = lib.validate(changed("points", change))
    assert report.error_ids == ["E03"], report
    assert errors_at(report, "E03") == ["mesh/coordinates"]
    assert "E03" not in lib.validate(base["points"]).error_ids


# ------------------------------------------------------------- E04

def test_e04_a_scalar_varies_by_row_or_not_at_all(changed, base):
    path = changed("family", lambda f: write_string_attr(
        f["cl"], "varies", "group:member"))
    report = lib.validate(path)
    assert report.error_ids == ["E04"]
    assert errors_at(report, "E04") == ["scalars/cl"]
    assert "E04" not in lib.validate(base["family"]).error_ids


# ------------------------------------------------------------- E05

def test_e05_node_counts_against_the_mesh(changed):
    path = changed("family", lambda f: write_int_attr(
        f["mesh"], "n_nodes", 5))
    report = lib.validate(path)
    assert report.error_ids == ["E05", "E08", "E24"]
    assert errors_at(report, "E05") == [
        "mesh/coordinates", "mesh/node_arrays/face",
        "mesh/node_arrays/pressure"]


def test_e05_cell_counts_against_the_mesh(changed, base):
    path = changed("family", lambda f: write_int_attr(
        f["mesh"], "n_cells", 3))
    report = lib.validate(path)
    assert report.error_ids == ["E05"]
    assert errors_at(report, "E05") == [
        "mesh/cell_arrays/face", "mesh/cell_arrays/flagged",
        "mesh/cell_arrays/velocity", "mesh/cell_types"]
    assert "E05" not in lib.validate(base["family"]).error_ids


# ------------------------------------------------------------- E08

def test_e08_points_coordinates_are_part_of_the_support_id(changed):
    def change(f):
        values = f["mesh/coordinates"][()]
        values[3, 0] += 1.0
        f["mesh/coordinates"][...] = values
    report = lib.validate(changed("points", change))
    assert report.error_ids == ["E08"]


def test_e08_float32_points_coordinates_hash_as_float64(changed):
    """The coordinates are widened before hashing, so storing the same
    values as float32 keeps the support id."""
    path = changed("points", lambda f: recreate(
        f, "mesh/coordinates", dtype="<f4"))
    with h5py.File(path, "r") as f:
        assert f["mesh/coordinates"].dtype == np.float32
        same = np.array_equal(f["mesh/coordinates"][()].astype("<f8"),
                              np.linspace(0.0, 0.2, 8).reshape(8, 1))
    report = lib.validate(path)
    assert report.error_ids == ([] if same else ["E08"])


# ------------------------------------------------------------- E11

def test_e11_units_absent_on_a_parameter(changed, base):
    def change(f):
        del f["mach"].attrs["units"]
    report = lib.validate(changed("family", change))
    assert report.error_ids == ["E11"]
    assert errors_at(report, "E11") == ["parameters/mach"]
    assert "E11" not in lib.validate(base["family"]).error_ids


def test_e11_units_that_do_not_parse(changed):
    def change(f):
        write_string_attr(f["cl"], "units", "m per")
        write_string_attr(f["mesh/coordinates"], "units", "m^^2")
        write_string_attr(f["mesh/node_arrays/pressure"], "units", "")
    report = lib.validate(changed("family", change))
    assert report.error_ids == ["E11"]
    assert errors_at(report, "E11") == [
        "mesh/coordinates", "mesh/node_arrays/pressure", "scalars/cl"]


def test_e11_labels_carry_no_units(base):
    report = lib.validate(base["family"])
    assert "E11" not in report.error_ids


# ------------------------------------------------------------- E12

def test_e12_the_relations_file_is_clean(base):
    report = lib.validate(base["relations"])
    assert "E12" not in report.error_ids


@pytest.mark.parametrize("path, attribute, value", [
    ("mesh/node_arrays/pressure_band", "of", "nothing"),
    ("mesh/node_arrays/pressure_band", "of", "face"),
    ("mesh/node_arrays/pressure_band", "of", "dp_dmach"),
    ("mesh/node_arrays/pressure_band", "units", "kPa"),
    ("cl_std", "units", "m"),
    ("mesh/node_arrays/dp_dmach", "with_respect_to", "member"),
    ("mesh/node_arrays/dp_dmach", "statistic", "band"),
    ("mesh/node_arrays/dcl_dx", "of", "pressure"),
    ("dcl_dmach", "of", "mach"),
])
def test_e12_a_relation_without_what_it_needs(changed, path, attribute,
                                              value):
    path_in_file = path
    mutated = changed("relations", lambda f: write_string_attr(
        f[path_in_file], attribute, value))
    report = lib.validate(mutated)
    concept = path if "/" in path else "scalars/" + path
    assert errors_at(report, "E12") == [concept], report
    assert report.error_ids == ["E12"], report


@pytest.mark.parametrize("path, attribute", [
    ("mesh/node_arrays/pressure_band", "level"),
    ("mesh/node_arrays/pressure_band", "method"),
    ("mesh/node_arrays/pressure_band", "of"),
    ("cl_std", "of"),
    ("mesh/node_arrays/dp_dmach", "of"),
])
def test_e12_a_relation_missing_an_attribute(changed, path, attribute):
    def change(f):
        del f[path].attrs[attribute]
    report = lib.validate(changed("relations", change))
    concept = path if "/" in path else "scalars/" + path
    assert errors_at(report, "E12") == [concept], report
    assert report.error_ids == ["E12"], report


def test_e12_a_derivative_with_respect_to_coordinates_is_a_node_array(
        changed):
    def change(f):
        write_string_attr(f["mesh/cell_arrays/velocity"], "of", "cl")
        write_string_attr(f["mesh/cell_arrays/velocity"],
                          "with_respect_to", "coordinates")
    report = lib.validate(changed("relations", change))
    assert errors_at(report, "E12") == ["mesh/cell_arrays/velocity"]


def test_e12_a_served_band_before_evaluation_needs_no_level(base):
    report = lib.validate(base["model"])
    assert report.errors == []


def test_e12_a_std_is_never_served(changed):
    path = changed("model", lambda f: write_string_attr(
        f["cl_band"], "statistic", "std"))
    report = lib.validate(path)
    assert errors_at(report, "E12") == ["scalars/cl_band"]


def test_e12_a_relation_with_another_varies_than_its_of(changed):
    def change(f):
        recreate(f, "mesh/node_arrays/dp_dmach",
                 values=np.ones((6, 1)), chunks=None,
                 dims=["mesh/node", "component_1"])
        write_string_attr(f["mesh/node_arrays/dp_dmach"], "varies", "none")
    report = lib.validate(changed("relations", change))
    assert report.error_ids == ["E12"], report
    assert errors_at(report, "E12") == ["mesh/node_arrays/dp_dmach"]


def test_e12_a_scalar_relation_of_a_constant_varies_like_it(changed, base):
    def change(f):
        recreate(f, "cl_std", values=np.float64(0.01), chunks=None,
                 dims=[])
        write_string_attr(f["cl_std"], "varies", "none")
        del f["cl_std"].attrs["coordinates"]
    report = lib.validate(changed("relations", change))
    assert report.error_ids == ["E12"], report
    assert errors_at(report, "E12") == ["scalars/cl_std"]
    assert "E12" not in lib.validate(base["relations"]).error_ids


def test_e12_of_belongs_to_a_relation(changed, base):
    path = changed("table", lambda f: write_string_attr(f["cl"], "of",
                                                        "cd"))
    report = lib.validate(path)
    assert report.error_ids == ["E12"]
    assert errors_at(report, "E12") == ["scalars/cl"]
    assert "E12" not in lib.validate(base["table"]).error_ids


@pytest.mark.parametrize("path, attribute", [
    ("cl_std", "level"), ("cl_std", "method"),
    ("mesh/node_arrays/dp_dmach", "method")])
def test_e12_level_and_method_belong_to_a_band(changed, path, attribute):
    def change(f):
        if attribute == "level":
            write_float_attr(f[path], "level", 0.9)
        else:
            write_string_attr(f[path], "method", "spread of samples")
    report = lib.validate(changed("relations", change))
    concept = path if "/" in path else "scalars/" + path
    assert report.error_ids == ["E12"], report
    assert errors_at(report, "E12") == [concept]


# ------------------------------------------------------------- E16

def test_e16_a_root_dataset_against_the_row_count(changed, base):
    path = changed("family", lambda f: f["mach"].resize((5,)))
    report = lib.validate(path)
    assert report.error_ids == ["E16"]
    assert errors_at(report, "E16") == ["parameters/mach"]
    with pytest.raises(lib.MestraError) as caught:
        lib.read(path)
    assert caught.value.rule == "E16"
    assert "E16" not in lib.validate(base["family"]).error_ids


def test_e16_a_row_varying_mesh_array_against_the_row_count(changed):
    path = changed("family", lambda f: f[
        "mesh/node_arrays/pressure"].resize((7, 6, 1)))
    report = lib.validate(path)
    assert errors_at(report, "E16") == ["mesh/node_arrays/pressure"]


# ------------------------------------------------------------- E18

def test_e18_public_information_missing_beside_a_private_group(changed,
                                                               base):
    def change(f):
        f.create_group("private").attrs["units_of_cl"] = 1
        del f["cl"].attrs["units"]
    report = lib.validate(changed("table", change))
    assert report.error_ids == ["E11", "E18"]
    assert errors_at(report, "E18") == ["scalars/cl"]

    def private_only(f):
        f.create_group("private")
    assert lib.validate(changed("table", private_only)).errors == []
    assert "E18" not in lib.validate(base["table"]).error_ids


def test_e19_the_rounding_attribute_is_int32_or_int64(tmp_path):
    ds = lib.Dataset(created="2026-10-16T00:00:00Z")
    ds.add_scalar("q", [1.0, 2.0], "1", round_bits=20)
    path = str(tmp_path / "q.mes")
    lib.write(ds, path)
    name = "_QuantizeBitRoundNumberOfSignificantBits"
    assert lib.validate(path).errors == []
    for dtype, fires in ((np.int64, False), (np.int16, True),
                         (np.float64, True)):
        with h5py.File(path, "r+") as f:
            f["q"].attrs.create(name, dtype(20))
        assert ("E19" in lib.validate(path).error_ids) == fires, dtype


# ------------------------------------------------------------- E20

def test_e20_float32_results_are_allowed(base):
    with h5py.File(base["table"], "r") as f:
        assert f["cd"].dtype == np.float32
    assert lib.validate(base["table"]).errors == []


@pytest.mark.parametrize("path, dtype, where", [
    ("mach", "<i4", "parameters/mach"),
    ("mesh/node_arrays/pressure", "<f2", "mesh/node_arrays/pressure"),
    ("member", "<f8", "labels/member"),
    ("run", None, "labels/run"),
])
def test_e20_dtypes_outside_the_table(changed, path, dtype, where):
    def change(f):
        if dtype is None:
            recreate(f, path, values=np.arange(6, dtype="<i4"))
        else:
            recreate(f, path, dtype=dtype)
    report = lib.validate(changed("family", change))
    assert errors_at(report, "E20") == [where], report


# ------------------------------------------------------------- E25

def test_e25_an_axis_carrying_the_wrong_dimension(changed, base):
    def change(f):
        pressure = f["mesh/node_arrays/pressure"]
        pressure.dims[1].detach_scale(f["mesh/node"])
        pressure.dims[1].attach_scale(f["mesh/cell_plus_one"])
    path = changed("family", change)
    report = lib.validate(path)
    assert report.error_ids == ["E25"]
    assert errors_at(report, "E25") == ["mesh/node_arrays/pressure"]
    with pytest.raises(lib.MestraError) as caught:
        lib.read(path)
    assert caught.value.rule == "E25"
    assert "E25" not in lib.validate(base["family"]).error_ids


def test_e27_a_group_dimensioned_dataset_is_chunked(changed, base):
    path = changed("family", lambda f: recreate(
        f, "mesh/coordinates", chunks=None))
    with h5py.File(path, "r") as f:
        assert f["mesh/coordinates"].chunks is None
    report = lib.validate(path)
    assert report.error_ids == ["E27"]
    assert errors_at(report, "E27") == ["mesh/coordinates"]
    assert "E27" not in lib.validate(base["family"]).error_ids


# ------------------------------------------------------------- E32

def test_e32_a_dictionary_may_not_use_inputs_at_its_top_level(changed,
                                                              base):
    path = changed("model", lambda f: f["callables/m1"].create_group(
        "inputs"))
    report = lib.validate(path)
    assert report.error_ids == ["E32"]
    assert errors_at(report, "E32") == ["callables/m1/inputs"]
    assert "E32" not in lib.validate(base["model"]).error_ids


# ------------------------------------------------------------- E33

@pytest.mark.parametrize("old, new, where", [
    ("cl", "group_cl", "scalars/group_cl"),
    ("span", "category_span", "parameters/category_span"),
    ("case", "component_3", "labels/component_3"),
])
def test_e33_names_reserved_in_the_root(changed, old, new, where):
    report = lib.validate(changed("table", lambda f: f.move(old, new)))
    assert errors_at(report, "E33") == [where], report


def test_e33_names_that_only_resemble_reserved_ones(changed):
    report = lib.validate(changed("table", lambda f: f.move("cl",
                                                            "groups")))
    assert "E33" not in report.error_ids


# ------------------------------------------------------------- E35

def test_e35_points_coordinates_do_not_vary(changed, base):
    path = changed("points", lambda f: write_string_attr(
        f["mesh/coordinates"], "varies", "row"))
    report = lib.validate(path)
    assert "E35" in report.error_ids
    assert errors_at(report, "E35") == ["mesh/coordinates"]
    assert "E35" not in lib.validate(base["points"]).error_ids


# ------------------------------------------------------------- E38

def test_e38_points_carry_no_cells(changed, base):
    def change(f):
        f["mesh"].create_dataset("cell_types", data=np.zeros(1, "u1"))
    report = lib.validate(changed("points", change))
    assert errors_at(report, "E38") == ["mesh"]
    assert "E38" not in lib.validate(base["points"]).error_ids


def test_e38_a_mesh_carries_its_three_cell_datasets(changed):
    def change(f):
        del f["mesh/cell_offsets"]
    report = lib.validate(changed("family", change))
    assert errors_at(report, "E38") == ["mesh"]


# ------------------------------------------------------------- E39

@pytest.mark.parametrize("case, path, attribute, where", [
    ("family", "cl", "varies", "scalars/cl"),
    ("family", "cl", "coordinates", "scalars/cl"),
    ("family", "cl", "source", "scalars/cl"),
    ("family", "mesh", "support_id", "mesh"),
    ("family", "member", "category", "labels/member"),
    ("model", "cl", "output", "scalars/cl"),
])
def test_e39_required_attributes(changed, base, case, path, attribute,
                                 where):
    def change(f):
        del f[path].attrs[attribute]
    report = lib.validate(changed(case, change))
    assert errors_at(report, "E39") == [where], report
    assert "E39" not in lib.validate(base[case]).error_ids


def test_e39_a_root_dataset_says_what_it_is(changed):
    def change(f):
        del f["mach"].attrs["role"]
    report = lib.validate(changed("family", change))
    assert errors_at(report, "E39") == ["mach"]


def test_e39_a_constant_carries_no_coordinates(changed, base):
    path = changed("table", lambda f: write_string_attr(
        f["s_ref"], "coordinates", "alpha case"))
    report = lib.validate(path)
    assert report.error_ids == ["E39"]
    assert errors_at(report, "E39") == ["scalars/s_ref"]
    with h5py.File(base["table"], "r") as f:
        assert "coordinates" not in f["s_ref"].attrs
    assert lib.validate(base["table"]).errors == []


# ------------------------------------------------------------- E43

def test_e43_only_row_group_and_category_dimensions_grow(changed, base):
    path = changed("family", lambda f: recreate(
        f, "mesh/node_arrays/face", chunks=(6, 1), maxshape=(None, 1)))
    report = lib.validate(path)
    assert report.error_ids == ["E43"]
    assert errors_at(report, "E43") == ["mesh/node_arrays/face"]
    with h5py.File(base["family"], "r") as f:
        assert f["group_member"].maxshape == (None,)
        assert f["category_flag"].maxshape == (None,)
    assert lib.validate(base["family"]).errors == []


def foreign_gradient(f, unlimited=False):
    """A later 1.x object: a dataset of a role this reader does not
    know, over a dimension of its own."""
    scale = make_scale(f, "parameter", 3, unlimited=unlimited)
    grad = f.create_dataset("grad_cl", data=np.ones((4, 3)),
                            chunks=(4, 3), maxshape=(None, 3),
                            track_times=False)
    grad.dims[0].attach_scale(f["row"])
    grad.dims[1].attach_scale(scale)
    write_string_attr(grad, "role", "gradient")


@pytest.mark.parametrize("unlimited", [False, True])
def test_e43_a_scale_only_foreign_objects_use_is_exempt(changed,
                                                        unlimited):
    path = changed("table", lambda f: foreign_gradient(f, unlimited))
    report = lib.validate(path)
    assert report.errors == []
    assert warnings_at(report, "W11") == ["grad_cl"]


def test_w11_an_unknown_dataset_in_the_mesh(changed, base):
    def change(f):
        extra = f["mesh"].create_dataset("vendor_flags",
                                         data=np.zeros((6, 1), "<i4"),
                                         track_times=False)
        extra.dims[0].attach_scale(f["mesh/node"])
        extra.dims[1].attach_scale(f["component_1"])
    report = lib.validate(changed("family", change))
    assert report.errors == []
    assert warnings_at(report, "W11") == ["mesh/vendor_flags"]
    assert "W11" not in lib.validate(base["family"]).warning_ids


# ------------------------------------------------------------- E45

def test_e45_an_inputs_entry_naming_nothing(changed, base):
    path = changed("model", lambda f: write_string_attr(
        f["callables/m1"], "inputs", "mach beta"))
    report = lib.validate(path)
    assert report.error_ids == ["E45"]
    assert errors_at(report, "E45") == ["callables/m1"]
    assert "E45" not in lib.validate(base["model"]).error_ids


def test_e45_inputs_may_name_scalars_and_fields(changed):
    path = changed("model", lambda f: write_string_attr(
        f["callables/m1"], "inputs",
        "alpha cl mach node_arrays/pressure"))
    assert lib.validate(path).errors == []


# ------------------------------------------------------------- E47

def test_e47_the_unit_of_generalisation_is_a_group_label(changed, base):
    path = changed("family", lambda f: write_string_attr(
        f, "generalisation_group", "status"))
    report = lib.validate(path)
    assert report.error_ids == ["E47"]
    assert errors_at(report, "E47") == [""]
    assert "E47" not in lib.validate(base["family"]).error_ids


def test_e47_a_run_group_is_a_group_label(changed, base):
    path = changed("transient", lambda f: write_string_attr(
        f["t"], "run_group", "split"))
    report = lib.validate(path)
    assert report.error_ids == ["E47"]
    assert errors_at(report, "E47") == ["parameters/t"]
    assert lib.validate(base["transient"]).errors == []


# ------------------------------------------------------------- E48

def test_e48_ids_are_unique(changed, base):
    path = changed("table", lambda f: f["case"].__setitem__(
        slice(None), np.array([101, 102, 102, 104])))
    report = lib.validate(path)
    assert report.error_ids == ["E48"]
    assert errors_at(report, "E48") == ["labels/case"]
    assert "E48" not in lib.validate(base["table"]).error_ids


def test_e48_string_ids_are_unique(changed):
    def change(f):
        f["run"][2] = b"a-1"
    report = lib.validate(changed("family", change))
    assert errors_at(report, "E48") == ["labels/run"]


# ------------------------------------------------------------- E49

def test_e49_a_served_slot_varies_by_row(changed, base):
    def change(f):
        for name in ("pressure", "pressure_band"):
            write_string_attr(f["mesh/node_arrays/" + name], "varies",
                              "none")
    report = lib.validate(changed("model", change))
    assert report.error_ids == ["E49"]
    assert errors_at(report, "E49") == ["mesh/node_arrays/pressure",
                                        "mesh/node_arrays/pressure_band"]
    assert "E49" not in lib.validate(base["model"]).error_ids


def test_e49_points_coordinates_are_never_served(changed):
    def change(f):
        old = f["mesh/coordinates"]
        attrs = {k: old.attrs[k] for k in ("units", "components")}
        old.dims[0].detach_scale(f["mesh/node"])
        old.dims[1].detach_scale(f["component_1"])
        del f["mesh/coordinates"]
        group = f["mesh"].create_group("coordinates")
        for key, value in (("role", "coordinates"), ("varies", "none"),
                           ("source", "callable:m1"),
                           ("output", "coordinates")):
            write_string_attr(group, key, value)
        write_string_attr(group, "units", attrs["units"].decode())
        write_int_attr(group, "components", int(attrs["components"]))
    report = lib.validate(changed("points", change))
    assert errors_at(report, "E49") == ["mesh/coordinates"]


# ------------------------------------------------------------- W01

def test_w01_a_split_that_divides_a_unit_of_generalisation(changed, base):
    path = changed("family", lambda f: f["split"].__setitem__(
        slice(None), np.array([0, 1, 0, 0, 1, 1], dtype="<i4")))
    report = lib.validate(path)
    assert report.errors == []
    assert warnings_at(report, "W01") == ["labels/split"]
    assert "m_a" in [f for f in report.warnings
                     if f.rule == "W01"][0].message
    assert "W01" not in lib.validate(base["family"]).warning_ids


def test_w01_a_split_that_divides_a_run(changed, base):
    def change(f):
        write_string_attr(f, "generalisation_group", "run")
        f["split"][...] = np.array([0, 1, 0, 1, 1], dtype="<i4")
    report = lib.validate(changed("transient", change))
    assert warnings_at(report, "W01") == ["labels/split"]
    assert lib.validate(base["transient"]).warnings == []


# ------------------------------------------------------------- W11

def test_w11_unknown_attributes_and_groups_name_where_they_are(changed,
                                                               base):
    def change(f):
        write_string_attr(f, "producer_build", "17")
        f["mesh"].create_group("vendor_extras")
        write_float_attr(f["mesh/node_arrays/pressure"], "gain", 2.0)
    report = lib.validate(changed("family", change))
    assert report.errors == []
    messages = {f.path: f.message for f in report.warnings
                if f.rule == "W11"}
    assert "producer_build" in messages[""]
    assert "gain" in messages["mesh/node_arrays/pressure"]
    assert "vendor_extras" in messages["mesh/vendor_extras"]
    assert warnings_at(report, "W11") == [
        "", "mesh/node_arrays/pressure", "mesh/vendor_extras"]
    assert "W11" not in lib.validate(base["family"]).warning_ids


# ------------------------------------------------------------- W12

def _big(tmp_path):
    ds = lib.Dataset(created="2026-10-16T00:00:00Z")
    ds.add_parameter("x", [0.0, 1.0, 2.0], "design", "1")
    mesh = ds.set_mesh(coordinates=np.zeros((40000, 1)), units="m",
                       dims=("node", "component"))
    mesh.add_node_array("big", np.zeros((3, 40000, 1)), "Pa",
                        ("row", "node", "component"))
    path = str(tmp_path / "big.mes")
    lib.write(ds, path)
    return path


@pytest.mark.parametrize("chunks", [(2, 40000, 1), (1, 10000, 1)])
def test_w12_a_chunk_that_is_not_the_default(tmp_path, chunks):
    path = _big(tmp_path)
    with h5py.File(path, "r+") as f:
        recreate(f, "mesh/node_arrays/big", chunks=chunks)
    report = lib.validate(path)
    assert report.errors == []
    assert warnings_at(report, "W12") == ["mesh/node_arrays/big"]


def test_w12_fewer_entries_than_the_bound_are_the_default(changed, base):
    """What an append leaves: a chunk smaller than the default for the
    grown length is still the default, so W12 stays silent."""
    path = changed("family", lambda f: recreate(
        f, "mesh/node_arrays/pressure", chunks=(1, 6, 1)))
    assert "W12" not in lib.validate(path).warning_ids
    path = changed("family", lambda f: recreate(f, "mach", chunks=(2,)))
    assert "W12" not in lib.validate(path).warning_ids
    path = changed("family", lambda f: recreate(f, "mach",
                                                chunks=(40000,)))
    assert warnings_at(lib.validate(path), "W12") == ["parameters/mach"]


def test_w12_the_axes_after_the_leading_one_are_whole(changed):
    path = changed("family", lambda f: recreate(
        f, "mesh/node_arrays/pressure", chunks=(1, 3, 1)))
    assert warnings_at(lib.validate(path), "W12") == [
        "mesh/node_arrays/pressure"]


def test_w12_after_the_node_block_the_axes_are_whole(tmp_path):
    ds = lib.Dataset(created="2026-10-16T00:00:00Z")
    ds.add_parameter("x", [0.0, 1.0], "design", "1")
    mesh = ds.set_mesh(coordinates=np.zeros((30000, 1)), units="m",
                       dims=("node", "component"))
    mesh.add_node_array("v", np.zeros((2, 30000, 3)), "m s-1",
                        ("row", "node", "component"))
    path = str(tmp_path / "v.mes")
    lib.write(ds, path)
    with h5py.File(path, "r") as f:
        assert f["mesh/node_arrays/v"].chunks == (1, 10922, 3)
    assert "W12" not in lib.validate(path).warning_ids
    with h5py.File(path, "r+") as f:
        recreate(f, "mesh/node_arrays/v", chunks=(1, 10922, 1))
    assert warnings_at(lib.validate(path), "W12") == ["mesh/node_arrays/v"]


# ------------------------------------------------------------- W18

def test_w18_two_rows_of_one_run_at_the_same_time(changed, base):
    path = changed("transient", lambda f: f["t"].__setitem__(
        1, 0.0))
    report = lib.validate(path)
    assert report.errors == []
    assert warnings_at(report, "W18") == ["parameters/t"]
    assert "r0" in [f for f in report.warnings
                    if f.rule == "W18"][0].message
    assert lib.validate(base["transient"]).warnings == []


def test_w18_needs_a_run_group(changed):
    def change(f):
        f["t"][1] = 0.0
        del f["t"].attrs["run_group"]
    assert "W18" not in lib.validate(changed("transient",
                                             change)).warning_ids


# ------------------------------------------------------------- W19

def test_w19_a_parameter_a_callable_reads_without_bounds(changed, base):
    def change(f):
        del f["alpha"].attrs["lower"]
    report = lib.validate(changed("model", change))
    assert report.errors == []
    assert warnings_at(report, "W19") == ["parameters/alpha"]
    assert "W19" not in lib.validate(base["model"]).warning_ids


def test_w19_needs_inputs(changed):
    def change(f):
        del f["alpha"].attrs["lower"]
        del f["callables/m1"].attrs["inputs"]
    assert "W19" not in lib.validate(changed("model",
                                             change)).warning_ids


# ------------------------------------------- kept rules, briefly

def test_e14_e30_e36_sources(changed):
    path = changed("model", lambda f: write_string_attr(
        f["cl"], "source", "callable:nope"))
    assert errors_at(lib.validate(path), "E14") == ["scalars/cl"]
    path = changed("model", lambda f: write_string_attr(
        f["cl"], "source", "callable:"))
    assert errors_at(lib.validate(path), "E36") == ["scalars/cl"]
    path = changed("model", lambda f: write_string_attr(
        f["cl"], "source", "data"))
    assert errors_at(lib.validate(path), "E30") == ["scalars/cl"]


def test_e10_codes_outside_the_table(changed):
    path = changed("family", lambda f: f["member"].__setitem__(
        0, 7))
    report = lib.validate(path)
    assert errors_at(report, "E10") == ["labels/member"]


def test_e42_a_scale_made_without_creation_order(changed, base):
    users = ("mesh/coordinates", "mesh/node_arrays/face",
             "mesh/node_arrays/pressure")

    def change(f):
        for path in users:
            f[path].dims[f[path].ndim - 2].detach_scale(f["mesh/node"])
        del f["mesh/node"]
        plain = f["mesh"].create_dataset("node", shape=(6,), dtype=">f4")
        plain.make_scale("This is a netCDF dimension but not a netCDF "
                         "variable.         6")
        for path in users:
            f[path].dims[f[path].ndim - 2].attach_scale(plain)
    report = lib.validate(changed("family", change))
    assert report.error_ids == ["E42"]
    assert errors_at(report, "E42") == ["mesh/node"]
    assert "E42" not in lib.validate(base["family"]).error_ids

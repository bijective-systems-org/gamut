"""Version 1 files, written and read back.

The four files of the plan: a `table` with constants; a `mesh` family
whose coordinates vary by member, with a node and a cell label sharing
a name and a per-row cell label; a `points` signal; and a zero-row
model whose scalar, field and band slots are served. Each is read back
by name, read in part and compared with slices of the full read,
opened by netCDF4 and by xarray, and validated.
"""

from __future__ import annotations

import copy

import h5py
import numpy as np
import pytest

from tests.v1_cases import (
    CASES,
    PACKAGE_DIR,
    QUAD_CONNECTIVITY,
    QUAD_OFFSETS,
    QUAD_TYPES,
    QUAD_XY,
    assert_this_package,
    content,
    lib,
    write_case,
)

pytestmark = pytest.mark.filterwarnings("error")


@pytest.fixture(scope="module")
def files(tmp_path_factory):
    directory = tmp_path_factory.mktemp("v1")
    return {name: write_case(name, directory) for name in CASES}


def test_the_package_under_test_is_this_checkout():
    assert_this_package()
    assert PACKAGE_DIR.name == "mestra"


# ------------------------------------------------------------- by name

def test_table_reads_back_by_name(files):
    with lib.read(files["table"]) as ds:
        assert ds.kind == "table" and ds.addons == []
        assert ds.row_count == 4
        assert list(ds.parameters) == ["alpha", "n_ribs", "span"]
        assert list(ds.labels) == ["case", "fidelity", "status"]
        assert list(ds.scalars) == ["cd", "cl", "l_ref", "s_ref"]
        span = ds.parameters["span"]
        assert span.role == "design" and span.units == "m"
        assert (span.lower, span.upper) == (8.0, 18.0)
        assert span.values().dims == ("row",)
        assert ds.parameters["n_ribs"].dtype == np.dtype("<i8")
        np.testing.assert_array_equal(ds.parameters["n_ribs"].values(),
                                      [4, 5, 6, 7])
        assert list(ds.labels["fidelity"].names().values) == [
            "panel", "rans", "panel", "rans"]
        np.testing.assert_array_equal(ds.labels["fidelity"].codes(),
                                      [0, 1, 0, 1])
        assert list(ds.labels["fidelity"].table) == ["panel", "rans"]
        np.testing.assert_array_equal(ds.labels["case"].names(),
                                      [101, 102, 103, 104])
        with pytest.raises(lib.MestraError):
            ds.labels["case"].codes()
        assert ds.labels["case"].table is None
        cl = ds.scalars["cl"]
        assert (cl.location, cl.role, cl.varies) == ("row", "scalar",
                                                     "row")
        assert cl.dtype == np.dtype("<f8") and not cl.served
        assert ds.scalars["cd"].dtype == np.dtype("<f4")
        s_ref = ds.scalars["s_ref"]
        assert s_ref.varies == "none" and s_ref.read().dims == ()
        assert float(s_ref.read().values) == 12.5
        assert s_ref.units == "m2"
        assert (ds.title, ds.license, ds.references, ds.source) == (
            "Wing table", "CC-BY-4.0", "doi:10.0000/example",
            "panel code 3.1")
        assert ds.notes["comment"] == "four runs"
        assert ds.notes["seed"] == 7
        np.testing.assert_array_equal(ds.notes["weights"], [0.5, 1.5])


def test_family_reads_back_by_name(files):
    with lib.read(files["family"]) as ds:
        assert ds.kind == "mesh" and ds.row_count == 6
        assert ds.generalisation_group == "member"
        mesh = ds.mesh
        assert (mesh.kind, mesh.n_nodes, mesh.n_cells) == ("mesh", 6, 2)
        coordinates = mesh.coordinates
        assert coordinates.varies == "group:member"
        assert coordinates.read().dims == ("group:member", "node",
                                           "component")
        assert coordinates.read().shape == (3, 6, 3)
        # Both arrays called face, one at the nodes and one at the cells.
        assert mesh.node_arrays["face"].location == "node"
        assert mesh.cell_arrays["face"].location == "cell"
        np.testing.assert_array_equal(
            mesh.node_arrays["face"].read().values[:, 0], [1, 1, 2, 1, 1, 2])
        np.testing.assert_array_equal(
            mesh.cell_arrays["face"].read().values[:, 0], [1, 2])
        flagged = mesh.cell_arrays["flagged"]
        assert (flagged.role, flagged.varies, flagged.category) == (
            "label", "row", "flag")
        assert flagged.read().dims == ("row", "cell", "component")
        types, offsets, connectivity = mesh.cells()
        np.testing.assert_array_equal(connectivity,
                                      [0, 1, 4, 3, 1, 2, 5, 4])
        velocity = mesh.cell_arrays["velocity"]
        assert velocity.components == 3 and velocity.units == "m s-1"
        assert mesh.support_id == lib.Dataset().set_mesh(
            (types, offsets, connectivity), coordinates=np.zeros((6, 3)),
            units="m", dims=("node", "component")).support_id


def test_points_reads_back_by_name(files):
    with lib.read(files["points"]) as ds:
        assert ds.kind == "points" and ds.addons == ["uncertainty"]
        assert ds.mesh.kind == "points" and ds.mesh.n_cells == 0
        assert ds.mesh.coordinates.varies == "none"
        assert ds.mesh.coordinates.read().shape == (8, 1)
        assert ds.mesh.node_arrays["dp_std"].statistic == "std"
        assert ds.mesh.node_arrays["dp_std"].of == "dp"
        with pytest.raises(lib.MestraError):
            ds.mesh.cells()


def test_model_reads_back_with_its_slots_served(files):
    with lib.read(files["model"]) as ds:
        assert ds.row_count == 0
        assert ds.kind == "mesh" and ds.addons == ["uncertainty", "model"]
        assert ds.parameters["mach"].values().shape == (0,)
        assert (ds.parameters["alpha"].lower,
                ds.parameters["alpha"].upper) == (0.0, 8.0)
        cl = ds.scalars["cl"]
        assert cl.served and cl.callable_id == "m1" and cl.output == "cl"
        band = ds.scalars["cl_band"]
        assert (band.statistic, band.of, band.level, band.method) == (
            "band", "cl", None, None)
        pressure = ds.mesh.node_arrays["pressure"]
        assert pressure.served and pressure.components == 1
        assert pressure.varies == "row" and pressure.dtype is None
        with pytest.raises(lib.MestraError) as caught:
            pressure.read()
        assert caught.value.rule == "E30"
        model = ds.callables["m1"]
        assert isinstance(model, lib.Affine)
        assert model.inputs == frozenset(["mach", "alpha"])
        assert ds.callable_inputs["m1"] == frozenset(["mach", "alpha"])


# ------------------------------------------------- selective reads

def _selections(n: int):
    return [slice(None), slice(1, None), slice(0, n, 2),
            np.array([0, n - 1]), [n - 1], np.array([], dtype=np.int64)]


@pytest.mark.parametrize("lazy", [True, False])
def test_selective_reads_equal_slices_of_the_full_read(files, lazy):
    with lib.read(files["family"], lazy=lazy) as ds:
        pressure = ds.mesh.node_arrays["pressure"]
        full = pressure.read().values
        for rows in _selections(6):
            for nodes in _selections(6):
                part = pressure.read(rows=rows, nodes=nodes).values
                expect = full[rows][:, nodes]
                np.testing.assert_array_equal(part, expect)
        velocity = ds.mesh.cell_arrays["velocity"]
        whole = velocity.read().values
        np.testing.assert_array_equal(
            velocity.read(rows=[1, 4], cells=[1]).values,
            whole[[1, 4]][:, [1]])
        cl = ds.scalars["cl"].read().values
        np.testing.assert_array_equal(
            ds.scalars["cl"].read(rows=[0, 3, 5]).values, cl[[0, 3, 5]])
        mach = ds.parameters["mach"].values().values
        np.testing.assert_array_equal(
            ds.parameters["mach"].values(slice(2, 4)).values, mach[2:4])
        names = ds.labels["run"].names().values
        assert list(ds.labels["run"].names([1, 2]).values) == list(
            names[[1, 2]])


def test_rows_of_a_group_varying_array_resolve_through_the_group(files):
    with lib.read(files["family"]) as ds:
        coordinates = ds.mesh.coordinates
        stored = coordinates.read().values
        codes = ds.labels["member"].codes().values
        per_row = coordinates.read(rows=slice(None))
        assert per_row.dims == ("row", "node", "component")
        np.testing.assert_array_equal(per_row.values, stored[codes])
        np.testing.assert_array_equal(
            coordinates.read(rows=[3], nodes=[0, 5]).values,
            stored[codes[[3]]][:, [0, 5]])
        np.testing.assert_array_equal(
            coordinates.read(instances=[2]).values, stored[[2]])
        assert coordinates.read(instances=[2]).dims[0] == "group:member"
        face = ds.mesh.node_arrays["face"]
        repeated = face.read(rows=[0, 4])
        assert repeated.dims == ("row", "node", "component")
        np.testing.assert_array_equal(
            repeated.values, np.stack([face.read().values] * 2))
        constant = ds.scalars["cl"].read(rows=[1]).values
        assert constant.shape == (1,)


@pytest.mark.parametrize("bad", [
    [3, 1], [1, 1], np.array([0.0, 1.0]), slice(4, 0, -1), 2,
    [True, False, True, False, True, False], np.array([[0, 1]]), [0, 6],
    [-1, 2]])
def test_selections_other_than_slices_and_increasing_indices_are_refused(
        files, bad):
    with lib.read(files["family"]) as ds:
        with pytest.raises(lib.MestraError) as caught:
            ds.mesh.node_arrays["pressure"].read(rows=bad)
        assert caught.value.rule == ""
        with pytest.raises(lib.MestraError):
            ds.mesh.node_arrays["pressure"].read(nodes=bad)


def test_selections_name_the_right_axis(files):
    with lib.read(files["family"]) as ds:
        with pytest.raises(lib.MestraError):
            ds.mesh.node_arrays["pressure"].read(cells=[0])
        with pytest.raises(lib.MestraError):
            ds.mesh.cell_arrays["velocity"].read(nodes=[0])
        with pytest.raises(lib.MestraError):
            ds.mesh.node_arrays["pressure"].read(instances=[0])
        with pytest.raises(lib.MestraError):
            ds.mesh.coordinates.read(rows=[0], instances=[0])
        with pytest.raises(lib.MestraError):
            ds.scalars["cl"].read(nodes=[0])


# ----------------------------------------------------- the handle

def test_a_dataset_is_a_handle(files):
    ds = lib.read(files["family"])
    twin = copy.copy(ds)
    held = ds.mesh.node_arrays["pressure"].read().values
    held[...] = -1.0                       # the caller's own copy
    again = ds.mesh.node_arrays["pressure"].read().values
    assert again[0, 0, 0] == 0.0
    twin.close()                          # copies share one open file
    with pytest.raises(lib.MestraError) as caught:
        ds.mesh.node_arrays["pressure"].read()
    assert caught.value.rule == ""
    assert again.shape == (6, 6, 1)       # arrays outlive the handle
    ds.close()                            # closing twice is harmless


def test_an_eager_read_keeps_its_values_after_close(files):
    ds = lib.read(files["family"], lazy=False)
    ds.close()
    assert ds.mesh.node_arrays["pressure"].read().shape == (6, 6, 1)
    assert ds.labels["member"].names().values[2] == "m_b"


def test_builder_arrays_are_copies_too():
    ds = CASES["table"]()
    first = ds.scalars["cl"].read().values
    first[0] = 99.0
    assert ds.scalars["cl"].read().values[0] == 0.1


# ---------------------------------------------- generic tools

@pytest.mark.parametrize("name", list(CASES))
def test_netcdf4_opens_each_file(files, name):
    netCDF4 = pytest.importorskip("netCDF4")
    assert_this_package()
    with netCDF4.Dataset(files[name]) as nc:
        assert "row" in nc.dimensions
        assert len(nc.dimensions["row"]) == {"table": 4, "family": 6,
                                             "points": 3, "model": 0}[name]
        if name != "model":
            assert set(nc.groups) >= {"mesh"} if name != "table" else True


@pytest.mark.parametrize("name", list(CASES))
def test_xarray_shows_the_run_table(files, name):
    xr = pytest.importorskip("xarray")
    assert_this_package()
    with lib.read(files[name]) as ds:
        rows = ds.row_count
        columns = list(ds.parameters) + list(ds.labels)
    with xr.open_dataset(files[name]) as opened:
        frame = opened.to_dataframe()
    assert len(frame) == rows
    for column in columns:
        assert column in frame.columns, (column, list(frame.columns))
    if name == "table":
        assert set(frame.columns) >= {"cl", "cd", "s_ref", "l_ref"}
        assert list(frame["s_ref"]) == [12.5] * 4
        assert list(frame["span"]) == [10.0, 12.0, 14.0, 16.0]


def test_xarray_datatree_adds_the_mesh(files):
    xr = pytest.importorskip("xarray")
    assert_this_package()
    tree = xr.open_datatree(files["family"])
    try:
        assert "mesh" in tree.children
        assert "pressure" in tree["mesh/node_arrays"].data_vars
        assert "face" in tree["mesh/cell_arrays"].data_vars
    finally:
        tree.close()


def test_to_xarray_decodes_the_labels(files):
    pytest.importorskip("xarray")
    with lib.read(files["family"]) as ds:
        view = ds.to_xarray()
    assert list(view["member"].values) == ["m_a", "m_a", "m_b", "m_b",
                                           "m_c", "m_c"]
    assert view["node_arrays/pressure"].dims == ("row", "node",
                                                 "component_1")


# ------------------------------------------------- the layout

def test_the_root_holds_the_run_table_with_roles(files):
    with h5py.File(files["family"], "r") as f:
        for name, role in (("mach", "condition"), ("member", "group"),
                           ("status", "status"), ("run", "id"),
                           ("split", "split"), ("cl", "scalar")):
            assert f[name].attrs["role"].decode() == role, name
        assert f["cl"].attrs["coordinates"].decode() == \
            "mach member run split status"
        assert f["cl"].attrs["varies"].decode() == "row"
        assert f.attrs["format"].decode() == "mestra/1"
        assert set(f["mesh"]) >= {"node_arrays", "cell_arrays",
                                  "coordinates", "cell_types"}
        assert f["mesh"].attrs["kind"].decode() == "mesh"
        assert f["row"].maxshape == (None,)
        assert f["group_member"].maxshape == (None,)
        assert f["category_member"].maxshape == (None,)
    with h5py.File(files["table"], "r") as f:
        assert f["s_ref"].shape == () and "coordinates" not in f["s_ref"].attrs
        assert f["s_ref"].attrs["varies"].decode() == "none"
        assert f.attrs["license"].decode() == "CC-BY-4.0"


def test_row_and_group_datasets_take_the_default_chunks(files):
    from mestra.encoding import default_chunks
    with h5py.File(files["family"], "r") as f:
        for path in ("mach", "member", "cl", "mesh/coordinates",
                     "mesh/node_arrays/pressure",
                     "mesh/cell_arrays/velocity"):
            dset = f[path]
            assert dset.chunks == default_chunks(dset.dtype.itemsize,
                                                 dset.shape), path
            assert (dset.compression, dset.compression_opts,
                    dset.shuffle) == ("gzip", 1, True), path
        assert f["mesh/node_arrays/face"].chunks is None
        assert f["mesh/cell_types"].chunks is None


def test_large_rows_are_chunked_by_node_blocks(tmp_path):
    ds = lib.Dataset(created="2026-10-16T00:00:00Z")
    ds.add_parameter("x", [0.0, 1.0], "design", "1")
    mesh = ds.set_mesh(coordinates=np.zeros((40000, 1)), units="m",
                       dims=("node", "component"))
    mesh.add_node_array("big", np.zeros((2, 40000, 1)), "Pa",
                        ("row", "node", "component"))
    path = str(tmp_path / "big.mes")
    lib.write(ds, path)
    with h5py.File(path, "r") as f:
        assert f["mesh/node_arrays/big"].chunks == (1, 32768, 1)
    assert lib.validate(path).warning_ids == []


def test_zero_rows_take_a_chunk_of_one(files):
    with h5py.File(files["model"], "r") as f:
        assert f["mach"].shape == (0,) and f["mach"].chunks == (1,)
        assert isinstance(f["cl"], h5py.Group)
        assert f["cl"].attrs["source"].decode() == "callable:m1"
        assert f["callables/m1"].attrs["inputs"].decode() == "alpha mach"


# ------------------------------------------------ rounding

def test_round_bits_keeps_the_relative_error_within_the_bound(tmp_path):
    rng = np.random.default_rng(1)
    values = (rng.standard_normal((3, 50)) * 1e3).astype(np.float32)
    values[0, 0] = np.nan
    values[0, 1] = np.inf
    values[0, 2] = -np.inf
    values[0, 3] = 0.0
    ds = lib.Dataset(created="2026-10-16T00:00:00Z")
    ds.add_parameter("x", [0.0, 1.0, 2.0], "design", "1")
    mesh = ds.set_mesh(coordinates=np.arange(50.0), units="m",
                       dims=("node",))
    mesh.add_node_array("p", values, "Pa", ("row", "node"),
                        dtype="float32", round_bits=10)
    path = str(tmp_path / "round.mes")
    lib.write(ds, path)
    with lib.read(path) as back:
        slot = back.mesh.node_arrays["p"]
        assert slot.significant_bits == 10 and slot.dtype == np.float32
        got = slot.read().values[:, :, 0]
    finite = np.isfinite(values) & (values != 0)
    error = np.abs(got[finite] - values[finite]) / np.abs(values[finite])
    assert error.max() <= 2.0 ** -11
    assert np.isnan(got[0, 0]) and got[0, 1] == np.inf
    assert got[0, 2] == -np.inf and got[0, 3] == 0.0
    with h5py.File(path, "r") as f:
        attr = f["mesh/node_arrays/p"].attrs[
            "_QuantizeBitRoundNumberOfSignificantBits"]
        assert int(attr) == 10 and attr.dtype == np.int32   # as netCDF-C


def test_round_bits_rounds_half_to_even():
    from mestra.model import _round
    # 1 + 2**-11 sits half way between two float32 values with 10
    # mantissa bits; half to even rounds it down to 1.0, and
    # 1 + 3 * 2**-11 up to 1 + 2**-9.
    values = np.array([1 + 2.0 ** -11, 1 + 3 * 2.0 ** -11], np.float32)
    got, bits = _round(values, 10, "x")
    assert bits == 10
    assert got[0] == np.float32(1.0)
    assert got[1] == np.float32(1 + 2.0 ** -9)


def test_round_bits_is_refused_where_it_cannot_apply():
    ds = lib.Dataset()
    with pytest.raises(lib.MestraError):
        ds.add_scalar("a", [1.0], "1", round_bits=0)
    with pytest.raises(lib.MestraError):
        ds.add_scalar("a", [1.0], "1", dtype="float32", round_bits=24)


# --------------------------------------------- rewriting

@pytest.mark.parametrize("name", list(CASES))
def test_write_of_read_is_the_same_file_in_content(files, name, tmp_path):
    again = str(tmp_path / ("again_%s.mes" % name))
    with lib.read(files[name]) as ds:
        lib.write(ds, again)
    assert content(again, layout=True) == content(files[name], layout=True)


def test_iteration_is_in_utf8_byte_order():
    ds = lib.Dataset()
    for name in ("b", "a", "Z", "9", "_"):
        ds.add_parameter(name, [1.0], "design", "1")
    assert list(ds.parameters) == ["9", "Z", "_", "a", "b"]


@pytest.mark.parametrize("name", list(CASES))
def test_each_file_validates_without_error(files, name):
    report = lib.validate(files[name])
    assert report.errors == [], report
    expected = {"family": ["W02"]}.get(name, [])
    assert report.warning_ids == expected, report


# ------------------------------------------------- builder defaults

def test_unbounded_parameters_record_their_observed_range():
    ds = lib.Dataset()
    span = ds.add_parameter("span", [3.0, np.nan, 1.0, 2.0], "design", "m")
    assert (span.lower, span.upper) == (1.0, 3.0)
    ribs = ds.add_parameter("ribs", [4, 9, 6, 5], "design", "1", upper=12)
    assert (ribs.lower, ribs.upper) == (4.0, 12.0)


def test_a_zero_row_parameter_keeps_only_the_bounds_it_is_given():
    ds = lib.Dataset()
    mach = ds.add_parameter("mach", [], "condition", "1")
    assert (mach.lower, mach.upper) == (None, None)
    alpha = ds.add_parameter("alpha", [], "condition", "degree", lower=0.0)
    assert (alpha.lower, alpha.upper) == (0.0, None)


def test_coordinates_may_be_float32(tmp_path):
    xyz = np.array([[0.0, 0.5], [1.0, 0.25], [1.5, 2.0]])
    built = {}
    for dtype in ("float32", "float64"):
        ds = lib.Dataset(created="2026-10-16T00:00:00Z")
        ds.add_parameter("x", [1.0], "design", "1")
        ds.set_mesh(coordinates=xyz, units="m",
                    dims=("node", "component"), dtype=dtype)
        path = str(tmp_path / ("%s.mes" % dtype))
        lib.write(ds, path)
        with lib.read(path) as back:
            assert back.mesh.coordinates.dtype == np.dtype(dtype)
            built[dtype] = back.mesh.support_id
    # Points coordinates are widened to float64 before hashing.
    assert built["float32"] == built["float64"]


def test_points_coordinates_have_one_to_three_components():
    ds = lib.Dataset()
    with pytest.raises(lib.MestraError) as caught:
        ds.set_mesh(coordinates=np.zeros((4, 4)), units="m",
                    dims=("node", "component"))
    assert caught.value.rule == "E03"


def test_a_relation_takes_the_varies_and_width_of_its_of():
    ds = CASES["family"]()
    with pytest.raises(lib.MestraError) as caught:
        ds.mesh.add_node_array("pressure_band", np.ones((6, 3)), "Pa",
                               ("node", "component"), statistic="band",
                               of="pressure", level=0.9, method="m")
    assert caught.value.rule == "E12"
    ds.add_constant("q", 2.0, "Pa")
    with pytest.raises(lib.MestraError) as caught:
        ds.add_scalar("q_std", [0.1] * 6, "Pa", statistic="std", of="q")
    assert caught.value.rule == "E12"
    # A derivative with respect to the coordinates is the exception.
    ds.mesh.add_node_array("dcl_dx", np.zeros((6, 6, 3)), "m-1",
                           ("row", "node", "component"), of="cl",
                           with_respect_to="coordinates")


def test_the_builder_owns_its_values():
    cells = [np.array(a) for a in (QUAD_TYPES, QUAD_OFFSETS,
                                   QUAD_CONNECTIVITY)]
    ribs = np.array([4, 5], dtype=np.int64)
    ids = np.array([7, 8], dtype=np.int64)
    ds = lib.Dataset()
    ds.add_parameter("ribs", ribs, "design", "1")
    ds.add_label("case", ids, "id")
    mesh = ds.set_mesh(tuple(cells), coordinates=QUAD_XY, units="m",
                       dims=("node", "component"))
    for array in cells + [ribs, ids]:
        array[...] = 0
    assert ds.parameters["ribs"].values().values.tolist() == [4, 5]
    assert ds.labels["case"].names().values.tolist() == [7, 8]
    assert mesh.cells()[2].tolist() == QUAD_CONNECTIVITY.tolist()

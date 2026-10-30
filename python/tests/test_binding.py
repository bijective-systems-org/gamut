"""The Python package over the shared core, end to end: each kind of study
the format holds, written with the library and read back with it."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

import gamut


def grid(nx, ny, scale=1.0):
    xs, ys = np.meshgrid(np.arange(nx) * scale, np.arange(ny) * scale)
    pts = np.stack([xs.ravel(), ys.ravel()], axis=1).astype(np.float64)
    conn = []
    for j in range(ny - 1):
        for i in range(nx - 1):
            a = j * nx + i
            conn += [a, a + 1, a + nx + 1, a + nx]
    n = (nx - 1) * (ny - 1)
    return pts, (np.full(n, 9, np.uint8), np.arange(0, 4 * n + 1, 4), np.array(conn))


def test_polar_table_one_run_at_a_time(tmp_path):
    p = str(tmp_path / "polar.gamut")
    with gamut.create(p, writer="tests",
                       parameters={"mach": {"units": "1", "role": "condition"},
                                   "alpha": {"units": "degree", "role": "condition"}},
                       labels={"status": {"role": "status", "categories": ["converged", "failed"]}},
                       scalars={"cl": "1", "cd": "1"},
                       constants={"s_ref": (12.5, "m2")}, title="Wing A polar") as s:
        for i in range(20):
            rid = s.add_run({"mach": 0.3 + 0.01 * i, "alpha": float(i % 5),
                             "status": "failed" if i == 7 else "converged",
                             "cl": 0.1 * (i % 5), "cd": np.float32(0.01)})
            assert rid == i
    with gamut.open(p) as f:
        assert f.kind == "data" and f.type == "table" and f.row_count == 20
        assert f.describe()["title"] == "Wing A polar"
        np.testing.assert_allclose(f.get_scalar("cl", rows=slice(0, 3)), [0.0, 0.1, 0.2])
        assert f.get_label("status", rows=7) == "failed"
        assert f.get_constant("s_ref") == 12.5
        table = f.table()
        assert list(table) == ["alpha", "mach", "status", "cd", "cl"]
        assert table["status"][7] == "failed"
        # cd was given as float32 and kept so; cl as float64.
        assert f.describe("cd")["dtype"] == "float32"
        assert f.describe("cl")["dtype"] == "float64"
        assert f.get_scalar("cd").dtype == np.float32
        np.testing.assert_array_equal(f.get_row_ids(), np.arange(20))


def test_append_in_place_continues_ids(tmp_path):
    p = str(tmp_path / "grow.gamut")
    with gamut.create(p, writer="tests", parameters={"x": "m"}, scalars={"y": "1"}) as s:
        s.add_runs({"x": [1.0, 2.0], "y": [10.0, 20.0]})
    for k in range(3):
        with gamut.open(p, mode="a") as s:
            assert s.add_run({"x": 3.0 + k, "y": 30.0}) == 2 + k
    with gamut.open(p) as f:
        assert f.row_count == 5
        np.testing.assert_array_equal(f.get_row_ids(), np.arange(5))
        assert np.isnan(f.get_scalar("y")).sum() == 0


def test_sweep_on_one_mesh_and_region_reads(tmp_path):
    p = str(tmp_path / "sweep.gamut")
    pts, cells = grid(4, 3)
    with gamut.create(p, writer="tests", mesh="shared", per="fixed",
                       coordinates={"units": "m", "axes": 2},
                       parameters={"mach": {"units": "1", "role": "condition"}},
                       mesh_labels={"zone": {"at": "cell", "categories": ["inlet", "wall"]}},
                       fields={"p": {"units": "Pa", "at": "node"},
                               "u": {"units": "m s-1", "at": "cell", "vector": "velocity", "axis": "x"},
                               "v": {"units": "m s-1", "at": "cell", "vector": "velocity", "axis": "y"}}) as s:
        s.set_mesh(pts, cells, labels={"zone": [0, 0, 0, 1, 1, 1]})
        p_runs = np.arange(6 * 12, dtype=np.float32).reshape(6, 12)
        s.add_runs({"mach": np.linspace(0.1, 0.6, 6)},
                   fields={"p": p_runs, "u": np.ones((6, 6)), "v": np.zeros((6, 6))})
    with gamut.open(p) as f:
        assert f.type == "shared"
        assert f.get_field("p", rows=2).shape == (12,)
        region = f.get_field("p", nodes=slice(0, 4))
        assert region.shape == (6, 4) and region.dtype == np.float32
        np.testing.assert_array_equal(region[:, 1], p_runs[:, 1])
        np.testing.assert_array_equal(f.get_points(), pts)
        assert f.get_mesh_label("zone").tolist() == [0, 0, 0, 1, 1, 1]
        assert f.categories("zone") == ["inlet", "wall"]
        with pytest.raises(gamut.GamutError, match="no category table"):
            f.categories("mach")
        assert f.related("u")["vector"] == ["u", "v"]
        types, offsets, conn = f.get_cells()
        assert types.tolist() == [9] * 6 and offsets[-1] == 24
        assert len(f.describe()["support_id"]) == 64


def test_topolink_family_per_member_geometry(tmp_path):
    p = str(tmp_path / "family.gamut")
    pts, cells = grid(3, 3)
    geometry = {m: (pts * (1 + k)).astype(np.float32) for k, m in enumerate(["c", "a", "b"])}
    with gamut.create(p, writer="TopoLink", mesh="shared", per="group:member",
                       coordinates={"units": "m", "axes": 2},
                       labels={"member": {"role": "group", "categories": ["a", "b", "c"]}},
                       generalisation_group="member",
                       parameters={"mach": {"units": "1", "role": "condition"}},
                       fields={"p": {"units": "Pa", "at": "node"}}) as s:
        s.set_mesh(cells=cells, n_nodes=9)
        # Members arrive out of their declared order, each run at two Mach
        # numbers; points are given with every run and kept once per member.
        members = ["c", "c", "a", "a"]
        s.add_runs({"member": members, "mach": [5.0, 8.0, 5.0, 8.0]},
                   fields={"p": np.ones((4, 9))},
                   points=[geometry[m] for m in members])
    with gamut.open(p, mode="a") as s:
        s.add_run({"member": "b", "mach": 5.0}, fields={"p": np.zeros(9)}, points=geometry["b"])
    with gamut.open(p) as f:
        assert f.row_count == 5 and f.type == "shared"
        assert f.describe("coordinates")["dtype"] == "float32"
        np.testing.assert_array_equal(f.get_points(row=0), geometry["c"])
        np.testing.assert_array_equal(f.get_points(row=3), geometry["a"])
        np.testing.assert_array_equal(f.get_points(row=4), geometry["b"])
        assert f.describe()["generalisation_group"] == "member"


def test_transient_rows_and_point_cloud(tmp_path):
    p = str(tmp_path / "transient.gamut")
    pts, cells = grid(3, 2)
    with gamut.create(p, writer="solver", mesh="shared", per="fixed",
                       coordinates={"units": "m", "axes": 2},
                       labels={"run": "group"},
                       parameters={"t": {"units": "s", "role": "time", "run_group": "run"},
                                   "mach": {"units": "1", "role": "condition"}},
                       fields={"p": {"units": "Pa", "at": "node"}}) as s:
        s.set_mesh(pts, cells)
        s.add_runs({"run": ["a", "a", "a", "b", "b"], "t": [0, 0.5, 1.0, 0, 0.7],
                    "mach": [0.8] * 3 + [0.9] * 2}, fields={"p": np.ones((5, 6))})
    with gamut.open(p) as f:
        assert f.addons == ["time"]
        assert f.get_label("run").tolist() == ["a", "a", "a", "b", "b"]
        assert f.describe("t")["run_group"] == "run"
    cloud = str(tmp_path / "taps.gamut")
    taps = np.array([[0.0], [0.1], [0.2], [0.5]])
    with gamut.create(cloud, writer="tunnel", mesh="shared", per="fixed",
                       coordinates={"units": "m", "axes": 1},
                       parameters={"alpha": {"units": "degree"}},
                       fields={"cp": {"units": "1", "at": "node"}}) as s:
        s.set_mesh(taps)
        s.add_runs({"alpha": [0.0, 4.0]}, fields={"cp": np.zeros((2, 4))})
    with gamut.open(cloud) as f:
        assert f.type == "shared" and f.get_points().shape == (4, 1)
        assert f.names("cell_fields") == []


def test_gradients_and_quantiles(tmp_path):
    p = str(tmp_path / "grad.gamut")
    with gamut.create(p, writer="adjoint",
                       parameters={"alpha": {"units": "degree"}, "mach": {"units": "1"}},
                       scalars={"cl": "1",
                                "cl_std": {"units": "1", "of": "cl", "statistic": "std"},
                                "cl_lo": {"units": "1", "of": "cl", "statistic": "quantile", "q": 0.025},
                                "cl_hi": {"units": "1", "of": "cl", "statistic": "quantile", "q": 0.975},
                                "dcl_dalpha": {"units": "degree-1", "of": "cl", "with_respect_to": "alpha"}}) as s:
        s.add_runs({"alpha": [0.0, 2.0], "mach": [0.5, 0.5], "cl": [0.1, 0.3],
                    "cl_std": [0.01, 0.01], "cl_lo": [0.08, 0.28], "cl_hi": [0.12, 0.32],
                    "dcl_dalpha": [0.1, 0.1]})
    with gamut.open(p) as f:
        assert f.addons == ["gradients", "uncertainty"]
        rel = f.related("cl")
        assert rel["std"] == "cl_std"
        assert rel["quantiles"] == {0.025: "cl_lo", 0.975: "cl_hi"}
        assert rel["derivatives"] == {"alpha": "dcl_dalpha"}


def test_changing_mesh_one_run_at_a_time(tmp_path):
    p = str(tmp_path / "remeshed.gamut")
    big_pts, big_cells = grid(4, 4)
    small_pts, small_cells = grid(2, 2)
    with gamut.create(p, writer="tests", mesh="changing", per="run",
                       coordinates={"units": "m", "axes": 2},
                       parameters={"r": {"units": "m"}},
                       fields={"p": {"units": "Pa", "at": "node"}}) as s:
        s.add_run({"r": 1.0}, fields={"p": np.arange(16.0)}, points=big_pts, cells=big_cells)
        s.add_run({"r": 2.0}, fields={"p": np.arange(4.0) + 100}, points=small_pts, cells=small_cells)
    with gamut.open(p) as f:
        assert f.type == "changing"
        np.testing.assert_array_equal(f.get_field("p", rows=1), np.arange(4.0) + 100)
        assert f.get_points(row=0).shape == (16, 2)
        types, offsets, conn = f.get_cells(row=1)
        assert types.tolist() == [9] and conn.tolist() == [0, 1, 3, 2]
        with pytest.raises(gamut.GamutError, match="changing mesh"):
            f.get_field("p")


def test_refusals_carry_rules(tmp_path):
    p = str(tmp_path / "bad.gamut")
    with pytest.raises(gamut.GamutError) as e:
        gamut.create(p, writer="t", parameters={"x": "m//s"})
    assert e.value.rule == "E7"
    with pytest.raises(gamut.GamutError) as e:
        gamut.create(p, writer="t", parameters={"p": "Pa"}, scalars={"p": "Pa"})
    assert e.value.rule == "E8"
    with gamut.create(p, writer="t", parameters={"x": "m"}) as s:
        with pytest.raises(gamut.GamutError) as e:
            s.add_run({"y": 1.0})
        assert e.value.rule == "E2"
        s.add_run({"x": 1.0})
    with gamut.open(p) as f:
        assert f.row_count == 1   # the refused run added nothing


def test_generic_tools_still_see_the_table(tmp_path):
    xr = pytest.importorskip("xarray")
    p = str(tmp_path / "t.gamut")
    with gamut.create(p, writer="t", parameters={"mach": "1"}, scalars={"cl": "1"}) as s:
        s.add_runs({"mach": [0.5, 0.6], "cl": [0.1, 0.2]})
    ds = xr.open_dataset(p)
    assert ds.sizes["row"] == 2 and list(ds["cl"].values) == [0.1, 0.2]


def test_parallel_reads_equal_serial_reads(tmp_path):
    p = str(tmp_path / "par.gamut")
    rng = np.random.default_rng(1)
    pts = np.zeros((70_000, 1))
    with gamut.create(p, writer="t", mesh="shared", per="fixed",
                       coordinates={"units": "m", "axes": 1}, parameters={"k": "1"},
                       fields={"a": {"units": "1", "at": "node"},
                               "b": {"units": "1", "at": "node", "precision": "float64"}}) as s:
        s.set_mesh(pts)
        s.add_runs({"k": np.arange(9.0)},
                   fields={"a": rng.normal(size=(9, 70_000)).astype(np.float32),
                           "b": rng.normal(size=(9, 70_000))})
    with gamut.open(p) as serial, gamut.open(p, threads=4) as par:
        for name in ("a", "b"):
            for rows, nodes in [(None, None), (slice(2, 7), None), (None, slice(65_000, 70_000)),
                                (3, slice(100, 66_000)), (slice(0, 1), slice(0, 1))]:
                np.testing.assert_array_equal(par.get_field(name, rows=rows, nodes=nodes),
                                              serial.get_field(name, rows=rows, nodes=nodes))
        # Index selections fall back to the serial path and still agree.
        np.testing.assert_array_equal(par.get_field("a", rows=[1, 5]),
                                      serial.get_field("a", rows=[1, 5]))


def test_select_where(tmp_path):
    p = str(tmp_path / "sel.gamut")
    with gamut.create(p, writer="t", parameters={"mach": "1", "alpha": "degree"},
                       labels={"status": {"role": "status", "categories": ["converged", "failed"]},
                               "model": {"role": "categorical", "categories": ["k-omega SST", "SA"]}},
                       scalars={"cl": "1"}) as s:
        s.add_runs({"mach": [0.3, 0.5, 0.7, 0.9], "alpha": [0.0, 2.0, 4.0, 6.0],
                    "status": ["converged", "failed", "converged", "converged"],
                    "model": ["SA", "k-omega SST", "SA", "k-omega SST"],
                    "cl": [0.1, np.nan, 0.5, 0.7]})
    with gamut.open(p) as f:
        assert f.select("mach > 0.4").tolist() == [1, 2, 3]
        assert f.select("mach > 0.4 and status == converged").tolist() == [2, 3]
        assert f.select('model == "k-omega SST" or alpha <= 0').tolist() == [0, 1, 3]
        assert f.select("not (mach > 0.4)").tolist() == [0]
        # Operators need no spaces; a single = is not one.
        assert f.select("(mach>0.4)and(alpha<5)").tolist() == [1, 2]
        assert f.select("status==converged").tolist() == [0, 2, 3]
        assert f.select('model!="k-omega SST"').tolist() == [0, 2]
        assert f.select("alpha>=-1e-9").tolist() == [0, 1, 2, 3]
        with pytest.raises(gamut.GamutError, match=r"operator \(==, !=, <, <=, >, >=\)"):
            f.select("mach = 0.5")
    with gamut.open(p) as f:
        # NaN compares false, so these differ on row 1.
        assert f.select("cl <= 0.5").tolist() == [0, 2]
        assert f.select("not (cl > 0.5)").tolist() == [0, 1, 2]
        for bad in ("mach >", "status < converged", "status == unknown", "nothing > 1",
                    "mach > big", "(mach > 1"):
            with pytest.raises(gamut.GamutError):
                f.select(bad)


def test_notes_private_and_units(tmp_path):
    pytest.importorskip("pint")
    p = str(tmp_path / "u.gamut")
    with gamut.create(p, writer="t", parameters={"altitude": "km", "speed": "m s-1"},
                       scalars={"q": "kPa"}) as s:
        s.notes["solver"] = "OpenFOAM v2406"
        s.notes["iterations"] = 4000
        s.notes["residual"] = 1.5e-6
        s.set_private("project", b"\x00\x01binary\xff")
        s.add_run({"altitude": (35000.0, "ft"), "speed": 250.0, "q": (101325.0, "Pa")})
    with gamut.open(p) as f:
        assert f.notes == {"iterations": 4000, "residual": 1.5e-6, "solver": "OpenFOAM v2406"}
        assert f.private_names() == ["project"]
        assert f.get_private("project") == b"\x00\x01binary\xff"
        np.testing.assert_allclose(f.get_parameter("altitude"), [10.668])
        np.testing.assert_allclose(f.get_parameter("altitude", units="ft"), [35000.0])
        np.testing.assert_allclose(f.get_parameter("speed", units="km h-1"), [900.0])
        np.testing.assert_allclose(f.get_scalar("q"), [101.325])
        with pytest.raises(gamut.GamutError, match="convert"):
            f.get_scalar("q", units="m")
    assert gamut.validate(p).findings == ()


def test_library_path_names_the_loaded_core():
    path = Path(gamut.library_path())
    assert path.is_file() and path.name == gamut._lib._library_name()


def test_portion_marking_is_free_text_under_64_kib(tmp_path):
    """The root attribute is read as written; one of 64 KiB or more is refused
    (HDF5's compact attribute storage at the writer's libver bounds) and the
    refusal leaves no file."""
    def write(path, marking):
        with gamut.create(path, writer="t", parameters={"x": "1"}, scalars={"y": "1"},
                           portion_marking=marking) as s:
            s.add_run({"x": 1.0, "y": 2.0})
    long_path = str(tmp_path / "long.gamut")
    write(long_path, "m" * 60000)
    with gamut.open(long_path) as f:
        assert f.describe()["portion_marking"] == "m" * 60000
    assert not gamut.validate(long_path).findings
    refused = str(tmp_path / "refused.gamut")
    with pytest.raises(gamut.GamutError, match="portion_marking"):
        write(refused, "m" * 65536)
    assert not os.path.exists(refused)


def test_package_and_core_versions_agree():
    from importlib import metadata
    try:
        installed = metadata.version("bijective-gamut")
    except metadata.PackageNotFoundError:
        pytest.skip("run from a source tree, not an installed package")
    assert installed == gamut.__version__ == gamut._lib.version()

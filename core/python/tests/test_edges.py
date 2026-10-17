"""Edges: a refused call must change nothing, an error must not hide
another, conversions happen only when asked, selections are read strictly,
and hostile sizes are capped before allocation."""

from __future__ import annotations

import ctypes
import os

import h5py
import numpy as np
import pytest

import mestra
from mestra import _lib


def grid(nx, ny):
    xs, ys = np.meshgrid(np.arange(nx, dtype=float), np.arange(ny, dtype=float))
    pts = np.stack([xs.ravel(), ys.ravel()], axis=1)
    conn = []
    for j in range(ny - 1):
        for i in range(nx - 1):
            a = j * nx + i
            conn += [a, a + 1, a + nx + 1, a + nx]
    n = (nx - 1) * (ny - 1)
    return pts, (np.full(n, 9, np.uint8), np.arange(0, 4 * n + 1, 4), np.array(conn))


# --- a refused call adds nothing --------------------------------------------------------


def test_refused_first_run_fixes_no_precision(tmp_path):
    p = str(tmp_path / "t.mes")
    with mestra.create(p, writer="t", labels={"status": "status"}, scalars={"s": "1"}) as s:
        with pytest.raises(mestra.MestraError) as e:
            s.add_run({"s": np.float32(1.0)})        # the label is missing
        assert e.value.rule == "E2"
        s.add_run({"s": 2.123456789, "status": "ok"})
    with mestra.open(p) as f:
        assert f.describe("s")["dtype"] == "float64"
        assert f.get_scalar("s")[0] == 2.123456789


def test_run_before_set_mesh_leaves_the_file_writable(tmp_path):
    p = str(tmp_path / "m.mes")
    pts, cells = grid(3, 2)
    with mestra.create(p, writer="t", mesh="shared", per="fixed",
                       coordinates={"units": "m", "axes": 2},
                       labels={"case": "group"}, parameters={"x": "m"},
                       fields={"q": {"units": "1", "at": "node"}}) as s:
        with pytest.raises(mestra.MestraError, match="set_mesh"):
            s.add_run({"x": 1.0, "case": "a"}, fields={"q": np.zeros(6)})
        s.set_mesh(pts, cells)
        s.add_run({"x": 1.0, "case": "a"}, fields={"q": np.zeros(6)})
    with mestra.open(p) as f:
        assert f.row_count == 1
    assert not mestra.validate(p).findings


def test_refused_set_mesh_can_be_retried(tmp_path):
    p = str(tmp_path / "m.mes")
    pts, cells = grid(3, 2)
    with mestra.create(p, writer="t", mesh="shared", per="fixed",
                       coordinates={"units": "m", "axes": 2}, parameters={"x": "m"},
                       mesh_labels={"zone": {"at": "cell", "categories": ["a", "b"]}}) as s:
        with pytest.raises(mestra.MestraError) as e:
            s.set_mesh(pts, cells, labels={"zone": [0, 7]})
        assert e.value.rule == "E9" and e.value.path == "cell_labels/zone"
        s.set_mesh(pts, cells, labels={"zone": [0, 1]})
        s.add_run({"x": 1.0})
    assert not mestra.validate(p).findings


# --- a declaration error surfaces as itself ---------------------------------------------


@pytest.mark.parametrize("fields, scalars, rule", [
    ({"q": {"units": "m//s", "at": "node"}}, {}, "E7"),
    ({"p": {"units": "Pa", "at": "node"}}, {"p": "Pa"}, "E8"),
])
def test_mesh_file_declaration_error_is_its_own(tmp_path, fields, scalars, rule):
    p = str(tmp_path / "bad.mes")
    with pytest.raises(mestra.MestraError) as e:
        mestra.create(p, writer="t", mesh="shared", per="fixed",
                      coordinates={"units": "m", "axes": 2}, fields=fields, scalars=scalars)
    assert e.value.rule == rule
    assert not os.path.exists(p)          # the half-declared file is removed


# --- parallel reads -------------------------------------------------------------------


def test_parallel_integer_reads_equal_serial(tmp_path):
    p = str(tmp_path / "par.mes")
    v = np.array([1e300, -1e300, np.nan, 3.7, -2.5, 1e9] * 12_000)
    with mestra.create(p, writer="t", mesh="shared", per="fixed",
                       coordinates={"units": "m", "axes": 1}, parameters={"k": "1"},
                       fields={"b": {"units": "1", "at": "node"}}) as s:
        s.set_mesh(np.zeros((v.size, 1)))
        s.add_runs({"k": [0.0, 1.0]}, fields={"b": np.stack([v, -v])})
    rows, sites = _lib.Selection(None, "rows"), _lib.Selection(None, "sites")
    with mestra.open(p) as serial, mestra.open(p, threads=4) as par:
        for dtype in (np.int32, np.int8, np.uint8, np.int64, np.float32):
            a = _lib.read(serial._handle(), "b", rows, sites, np.dtype(dtype))
            c = _lib.read(par._handle(), "b", rows, sites, np.dtype(dtype))
            assert a.tobytes() == c.tobytes(), dtype


# --- support id from the stored precision ----------------------------------------------


def test_float32_point_cloud_hashes_stored_points(tmp_path):
    p = str(tmp_path / "cloud.mes")
    taps = np.array([[0.1], [0.2], [0.3000001]])        # float64, not float32-exact
    with mestra.create(p, writer="t", mesh="shared", per="fixed",
                       coordinates={"units": "m", "axes": 1, "precision": "float32"},
                       parameters={"a": "degree"}, fields={"cp": {"units": "1", "at": "node"}}) as s:
        s.set_mesh(taps)
        s.add_run({"a": 0.0}, fields={"cp": np.zeros(3)})
    assert not mestra.validate(p).findings           # E11 if the id came from float64


# --- changing meshes without cells ------------------------------------------------------


def test_changing_mesh_without_cells_writes_no_cell_objects(tmp_path):
    p = str(tmp_path / "clouds.mes")
    with mestra.create(p, writer="t", mesh="changing", per="run",
                       coordinates={"units": "m", "axes": 2}, parameters={"r": "m"},
                       fields={"q": {"units": "1", "at": "node"}}) as s:
        s.add_run({"r": 1.0}, fields={"q": np.arange(3.0)}, points=np.zeros((3, 2)))
        s.add_run({"r": 2.0}, fields={"q": np.arange(5.0)}, points=np.ones((5, 2)))
        pts, cells = grid(2, 2)
        with pytest.raises(mestra.MestraError, match="have no cells"):
            s.add_run({"r": 3.0}, fields={"q": np.arange(4.0)}, points=pts, cells=cells)
    assert not mestra.validate(p).findings
    with h5py.File(p, "r") as h:
        cell_things = [k for k in h["mesh"] if "cell" in k or k == "index"]
        assert cell_things == []
    with mestra.open(p) as f:
        assert f.get_points(row=1).shape == (5, 2)
        types, offsets, conn = f.get_cells(row=1)
        assert types.size == offsets.size == conn.size == 0
        np.testing.assert_array_equal(f.get_field("q", rows=1), np.arange(5.0))


def test_changing_mesh_without_cells_refuses_cell_fields(tmp_path):
    p = str(tmp_path / "clouds.mes")
    with mestra.create(p, writer="t", mesh="changing", per="run",
                       coordinates={"units": "m", "axes": 2}, parameters={"r": "m"},
                       fields={"q": {"units": "1", "at": "cell"}}) as s:
        with pytest.raises(mestra.MestraError, match="without cells has no cell fields"):
            s.add_run({"r": 1.0}, points=np.zeros((3, 2)))


# --- conversions only when asked --------------------------------------------------------


def test_as_given_float32_refuses_later_float64(tmp_path):
    p = str(tmp_path / "t.mes")
    with mestra.create(p, writer="t", parameters={"x": "m"}, scalars={"s": "1"}) as s:
        s.add_run({"x": 1.0, "s": np.float32(1.0)})
        with pytest.raises(mestra.MestraError) as e:
            s.add_run({"x": 2.0, "s": 1.0000001})
        assert e.value.rule == "E4"
        s.add_run({"x": 2.0, "s": np.float32(1.5)})
    with mestra.open(p) as f:
        assert f.row_count == 2


def test_round_bits_checked_against_the_resolved_precision(tmp_path):
    p = str(tmp_path / "t.mes")
    with mestra.create(p, writer="t", parameters={"x": "m"},
                       scalars={"s": {"units": "1", "round_bits": 40}}) as s:
        with pytest.raises(mestra.MestraError, match="round_bits"):
            s.add_run({"x": 1.0, "s": np.float32(1.0)})
        s.add_run({"x": 1.0, "s": 1.0})


def test_floats_are_not_taken_as_integers(tmp_path):
    p = str(tmp_path / "t.mes")
    with mestra.create(p, writer="t", parameters={"n": {"units": "1", "dtype": "int64"}},
                       labels={"status": {"role": "status", "categories": ["a", "b"]}}) as s:
        with pytest.raises(mestra.MestraError) as e:
            s.add_run({"n": 2.0, "status": "a"})
        assert e.value.rule == "E4"
        h = s._handle()
        _lib.call("mes_batch_begin", h, 1)
        _lib.call("mes_batch_values", h, b"n", _lib.MES_INT64,
                  np.array([2], np.int64).ctypes.data_as(ctypes.c_void_p), 1)
        _lib.call("mes_batch_values", h, b"status", _lib.MES_FLOAT64,
                  np.array([1.0]).ctypes.data_as(ctypes.c_void_p), 1)
        with pytest.raises(mestra.MestraError) as e:
            _lib.call("mes_batch_commit", h, ctypes.byref(ctypes.c_int64()))
        assert e.value.rule == "E4"


# --- strings and selections -------------------------------------------------------------


def test_nul_in_a_string_is_refused(tmp_path):
    with pytest.raises(mestra.MestraError, match="NUL"):
        mestra.create(str(tmp_path / "a.mes"), writer="t", parameters={"x\x00y": "m"})
    with mestra.create(str(tmp_path / "b.mes"), writer="t", labels={"case": "group"},
                       parameters={"x": "m"}) as s:
        with pytest.raises(mestra.MestraError, match="NUL"):
            s.add_run({"x": 1.0, "case": "bad\x00name"})
        s.add_run({"x": 1.0, "case": "good"})


def test_selections_outside_the_forms_are_refused(tmp_path):
    p = str(tmp_path / "t.mes")
    with mestra.create(p, writer="t", parameters={"x": "m"}) as s:
        s.add_runs({"x": [1.0, 2.0, 3.0]})
    with mestra.open(p) as f:
        with pytest.raises(mestra.MestraError, match="integers"):
            f.get_parameter("x", rows=[0.9, 1.7])
        with pytest.raises(mestra.MestraError, match="integers"):
            f.get_parameter("x", rows=np.array([True, False, True]))
        assert f.get_parameter("x", rows=[]).size == 0
    c = str(tmp_path / "c.mes")
    pts, cells = grid(2, 2)
    with mestra.create(c, writer="t", mesh="changing", per="run",
                       coordinates={"units": "m", "axes": 2}, parameters={"r": "m"},
                       fields={"q": {"units": "1", "at": "node"}}) as s:
        s.add_run({"r": 1.0}, fields={"q": np.zeros(4)}, points=pts, cells=cells)
    with mestra.open(c) as f:
        with pytest.raises(mestra.MestraError, match="one row at a time"):
            f.get_field("q", rows=slice(0, 1))
        with pytest.raises(mestra.MestraError, match="one run at a time"):
            f.get_cells()                         # one row, but no row given
        with pytest.raises(mestra.MestraError, match="integer"):
            f.get_cells(row=0.0)
        assert f.get_cells(row=0)[0].tolist() == [9]


def test_one_batch_cannot_give_a_member_two_geometries(tmp_path):
    p = str(tmp_path / "fam.mes")
    pts, cells = grid(2, 2)
    with mestra.create(p, writer="t", mesh="shared", per="group:member",
                       coordinates={"units": "m", "axes": 2},
                       labels={"member": "group"}, parameters={"mach": "1"}) as s:
        s.set_mesh(cells=cells, n_nodes=4)
        with pytest.raises(mestra.MestraError, match="two different geometries"):
            s.add_runs({"member": ["a", "a"], "mach": [1.0, 2.0]}, points=[pts, pts * 2])
        s.add_runs({"member": ["a", "a"], "mach": [1.0, 2.0]}, points=[pts, pts.copy()])
    with mestra.open(p) as f:
        assert f.row_count == 2


def test_counts_that_overflow_are_refused(tmp_path):
    with mestra.create(str(tmp_path / "t.mes"), writer="t", parameters={"x": "m"}) as s:
        h = s._handle()
        _lib.call("mes_batch_begin", h, 1)
        one = np.zeros(1)
        with pytest.raises(mestra.MestraError, match="too large"):
            _lib.call("mes_batch_values", h, b"x", _lib.MES_FLOAT64,
                      one.ctypes.data_as(ctypes.c_void_p), (1 << 61) + 1)
        s.add_run({"x": 1.0})


def test_scattered_selections_read_by_gathering(tmp_path):
    # Many blocks (more than 64 index runs across the axes) are read as one
    # box and gathered; the result must equal the whole read, indexed.
    p = str(tmp_path / "g.mes")
    rng = np.random.default_rng(3)
    with mestra.create(p, writer="t", mesh="shared", per="run",
                       coordinates={"units": "m", "axes": 3}, parameters={"k": "1"},
                       fields={"a": {"units": "1", "at": "node"}}) as s:
        s.set_mesh(n_nodes=300)
        s.add_runs({"k": np.arange(70.0)}, fields={"a": rng.normal(size=(70, 300))},
                   points=list(rng.normal(size=(70, 300, 3))))
    rows = np.sort(rng.choice(70, 40, replace=False))
    nodes = np.sort(rng.choice(300, 100, replace=False))
    with mestra.open(p) as f:
        whole = f.get_field("a")
        np.testing.assert_array_equal(f.get_field("a", rows=rows, nodes=nodes),
                                      whole[np.ix_(rows, nodes)])
        pts = np.stack([f.get_points(row=int(r)) for r in range(70)])
        h = f._handle()
        got = _lib.read(h, "coordinates", _lib.Selection(rows, "rows"),
                        _lib.Selection(nodes, "nodes"), np.dtype(np.float64))
        np.testing.assert_array_equal(got, pts[np.ix_(rows, nodes)])

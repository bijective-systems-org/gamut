"""Edges: a refused call must change nothing, an error must not hide
another, conversions happen only when asked, selections are read strictly,
and hostile sizes are capped before allocation."""

from __future__ import annotations

import ctypes
import os

import h5py
import numpy as np
import pytest

import gamut
from gamut import _lib


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
    p = str(tmp_path / "t.gamut")
    with gamut.create(p, writer="t", labels={"status": "status"}, scalars={"s": "1"}) as s:
        with pytest.raises(gamut.GamutError) as e:
            s.add_run({"s": np.float32(1.0)})        # the label is missing
        assert e.value.rule == "E2"
        s.add_run({"s": 2.123456789, "status": "ok"})
    with gamut.open(p) as f:
        assert f.describe("s")["dtype"] == "float64"
        assert f.get_scalar("s")[0] == 2.123456789


def test_a_mesh_without_per_is_refused_by_the_core(tmp_path):
    p = tmp_path / "m.gamut"
    with pytest.raises(gamut.GamutError, match="needs per") as e:
        gamut.create(str(p), writer="t", mesh="shared")
    assert e.value.rule == "E6"
    assert not p.exists()


@pytest.mark.parametrize("offsets", [[0], [0, 4, 9]])
def test_cell_offsets_need_one_more_than_cells(tmp_path, offsets):
    pts, _ = grid(2, 2)
    with gamut.create(str(tmp_path / "m.gamut"), writer="t", mesh="shared", per="fixed",
                       coordinates={"units": "m", "axes": 2}) as s:
        with pytest.raises(gamut.GamutError, match="one more entry") as e:
            s.set_mesh(pts, ([9], offsets, [0, 1, 3, 2]))
        assert e.value.rule == "E5"
        s.set_mesh(pts, ([9], [0, 4], [0, 1, 3, 2]))


def test_run_before_set_mesh_leaves_the_file_writable(tmp_path):
    p = str(tmp_path / "m.gamut")
    pts, cells = grid(3, 2)
    with gamut.create(p, writer="t", mesh="shared", per="fixed",
                       coordinates={"units": "m", "axes": 2},
                       labels={"case": "group"}, parameters={"x": "m"},
                       fields={"q": {"units": "1", "at": "node"}}) as s:
        with pytest.raises(gamut.GamutError, match="set_mesh"):
            s.add_run({"x": 1.0, "case": "a"}, fields={"q": np.zeros(6)})
        s.set_mesh(pts, cells)
        s.add_run({"x": 1.0, "case": "a"}, fields={"q": np.zeros(6)})
    with gamut.open(p) as f:
        assert f.row_count == 1
    assert not gamut.validate(p).findings


def test_refused_set_mesh_can_be_retried(tmp_path):
    p = str(tmp_path / "m.gamut")
    pts, cells = grid(3, 2)
    with gamut.create(p, writer="t", mesh="shared", per="fixed",
                       coordinates={"units": "m", "axes": 2}, parameters={"x": "m"},
                       mesh_labels={"zone": {"at": "cell", "categories": ["a", "b"]}}) as s:
        with pytest.raises(gamut.GamutError) as e:
            s.set_mesh(pts, cells, labels={"zone": [0, 7]})
        assert e.value.rule == "E9" and e.value.path == "cell_labels/zone"
        s.set_mesh(pts, cells, labels={"zone": [0, 1]})
        s.add_run({"x": 1.0})
    assert not gamut.validate(p).findings


# --- a declaration error surfaces as itself ---------------------------------------------


@pytest.mark.parametrize("fields, scalars, rule", [
    ({"q": {"units": "m//s", "at": "node"}}, {}, "E7"),
    ({"p": {"units": "Pa", "at": "node"}}, {"p": "Pa"}, "E8"),
])
def test_mesh_file_declaration_error_is_its_own(tmp_path, fields, scalars, rule):
    p = str(tmp_path / "bad.gamut")
    with pytest.raises(gamut.GamutError) as e:
        gamut.create(p, writer="t", mesh="shared", per="fixed",
                      coordinates={"units": "m", "axes": 2}, fields=fields, scalars=scalars)
    assert e.value.rule == rule
    assert not os.path.exists(p)          # the half-declared file is removed


# --- parallel reads -------------------------------------------------------------------


def test_parallel_integer_reads_equal_serial(tmp_path):
    p = str(tmp_path / "par.gamut")
    v = np.array([1e300, -1e300, np.nan, 3.7, -2.5, 1e9] * 12_000)
    with gamut.create(p, writer="t", mesh="shared", per="fixed",
                       coordinates={"units": "m", "axes": 1}, parameters={"k": "1"},
                       fields={"b": {"units": "1", "at": "node"}}) as s:
        s.set_mesh(np.zeros((v.size, 1)))
        s.add_runs({"k": [0.0, 1.0]}, fields={"b": np.stack([v, -v])})
    rows, sites = _lib.Selection(None, "rows"), _lib.Selection(None, "sites")
    with gamut.open(p) as serial, gamut.open(p, threads=4) as par:
        for dtype in (np.int32, np.int8, np.uint8, np.int64, np.float32):
            a = _lib.read(serial._handle(), "b", rows, sites, np.dtype(dtype))
            c = _lib.read(par._handle(), "b", rows, sites, np.dtype(dtype))
            assert a.tobytes() == c.tobytes(), dtype


# --- support id from the stored precision ----------------------------------------------


def test_float32_point_cloud_hashes_stored_points(tmp_path):
    p = str(tmp_path / "cloud.gamut")
    taps = np.array([[0.1], [0.2], [0.3000001]])        # float64, not float32-exact
    with gamut.create(p, writer="t", mesh="shared", per="fixed",
                       coordinates={"units": "m", "axes": 1, "precision": "float32"},
                       parameters={"a": "degree"}, fields={"cp": {"units": "1", "at": "node"}}) as s:
        s.set_mesh(taps)
        s.add_run({"a": 0.0}, fields={"cp": np.zeros(3)})
    assert not gamut.validate(p).findings           # E11 if the id came from float64


# --- changing meshes without cells ------------------------------------------------------


def test_changing_mesh_without_cells_writes_no_cell_objects(tmp_path):
    p = str(tmp_path / "clouds.gamut")
    with gamut.create(p, writer="t", mesh="changing", per="run",
                       coordinates={"units": "m", "axes": 2}, parameters={"r": "m"},
                       fields={"q": {"units": "1", "at": "node"}}) as s:
        s.add_run({"r": 1.0}, fields={"q": np.arange(3.0)}, points=np.zeros((3, 2)))
        s.add_run({"r": 2.0}, fields={"q": np.arange(5.0)}, points=np.ones((5, 2)))
        pts, cells = grid(2, 2)
        with pytest.raises(gamut.GamutError, match="have no cells"):
            s.add_run({"r": 3.0}, fields={"q": np.arange(4.0)}, points=pts, cells=cells)
    assert not gamut.validate(p).findings
    with h5py.File(p, "r") as h:
        cell_things = [k for k in h["mesh"] if "cell" in k or k == "index"]
        assert cell_things == []
    with gamut.open(p) as f:
        assert f.get_points(row=1).shape == (5, 2)
        types, offsets, conn = f.get_cells(row=1)
        assert types.size == offsets.size == conn.size == 0
        np.testing.assert_array_equal(f.get_field("q", rows=1), np.arange(5.0))


def test_changing_mesh_without_cells_refuses_cell_fields(tmp_path):
    p = str(tmp_path / "clouds.gamut")
    with gamut.create(p, writer="t", mesh="changing", per="run",
                       coordinates={"units": "m", "axes": 2}, parameters={"r": "m"},
                       fields={"q": {"units": "1", "at": "cell"}}) as s:
        with pytest.raises(gamut.GamutError, match="without cells has no cell fields"):
            s.add_run({"r": 1.0}, points=np.zeros((3, 2)))


# --- conversions only when asked --------------------------------------------------------


def test_as_given_float32_refuses_later_float64(tmp_path):
    p = str(tmp_path / "t.gamut")
    with gamut.create(p, writer="t", parameters={"x": "m"}, scalars={"s": "1"}) as s:
        s.add_run({"x": 1.0, "s": np.float32(1.0)})
        with pytest.raises(gamut.GamutError) as e:
            s.add_run({"x": 2.0, "s": 1.0000001})
        assert e.value.rule == "E4"
        s.add_run({"x": 2.0, "s": np.float32(1.5)})
    with gamut.open(p) as f:
        assert f.row_count == 2


def test_round_bits_checked_against_the_resolved_precision(tmp_path):
    p = str(tmp_path / "t.gamut")
    with gamut.create(p, writer="t", parameters={"x": "m"},
                       scalars={"s": {"units": "1", "round_bits": 40}}) as s:
        with pytest.raises(gamut.GamutError, match="round_bits"):
            s.add_run({"x": 1.0, "s": np.float32(1.0)})
        s.add_run({"x": 1.0, "s": 1.0})


def test_floats_are_not_taken_as_integers(tmp_path):
    p = str(tmp_path / "t.gamut")
    with gamut.create(p, writer="t", parameters={"n": {"units": "1", "dtype": "int64"}},
                       labels={"status": {"role": "status", "categories": ["a", "b"]}}) as s:
        with pytest.raises(gamut.GamutError) as e:
            s.add_run({"n": 2.0, "status": "a"})
        assert e.value.rule == "E4"
        h = s._handle()
        _lib.call("gamut_batch_begin", h, 1)
        _lib.call("gamut_batch_values", h, b"n", _lib.GAMUT_INT64,
                  np.array([2], np.int64).ctypes.data_as(ctypes.c_void_p), 1)
        _lib.call("gamut_batch_values", h, b"status", _lib.GAMUT_FLOAT64,
                  np.array([1.0]).ctypes.data_as(ctypes.c_void_p), 1)
        with pytest.raises(gamut.GamutError) as e:
            _lib.call("gamut_batch_commit", h, ctypes.byref(ctypes.c_int64()))
        assert e.value.rule == "E4"



def test_a_number_given_as_text_is_named_as_such(tmp_path):
    # A spreadsheet's "4.0" left as text: the refusal says so, rather than
    # that the run has no value or that the name is not a label.
    p = str(tmp_path / "t.gamut")
    with gamut.create(p, writer="t", parameters={"alpha": "degree"}, scalars={"cl": "1"}) as s:
        with pytest.raises(gamut.GamutError, match=r'alpha is a parameter, which takes numbers, '
                                                   r'and was given text \("4.0"\)'):
            s.add_run({"alpha": "4.0", "cl": 0.1})
        with pytest.raises(gamut.GamutError, match=r'cl is a result, which takes numbers'):
            s.add_run({"alpha": 4.0, "cl": "0.15"})
        s.add_run({"alpha": 4.0, "cl": 0.15})


def test_runs_from_a_dataframe(tmp_path):
    # A run table read from a spreadsheet with pandas goes in as it is, and
    # comes back out the same way.
    pd = pytest.importorskip("pandas")
    df = pd.DataFrame({"alpha": [0.0, 2.0, 4.0], "status": ["converged", "converged", "failed"],
                       "cl": [0.0, 0.22, np.nan]})
    p = str(tmp_path / "t.gamut")
    with gamut.create(p, writer="t", parameters={"alpha": "degree"}, scalars={"cl": "1"},
                       labels={"status": {"role": "status", "categories": ["converged", "failed"]}}) as s:
        assert s.add_runs(df) == [0, 1, 2]
        assert s.add_run(df.iloc[1]) == 3
    with gamut.open(p) as s:
        back = pd.DataFrame(s.table())
    assert back["status"].tolist() == ["converged", "converged", "failed", "converged"]
    assert np.array_equal(back["cl"].to_numpy(), [0.0, 0.22, np.nan, 0.22], equal_nan=True)

# --- strings and selections -------------------------------------------------------------


def test_nul_in_a_string_is_refused(tmp_path):
    with pytest.raises(gamut.GamutError, match="NUL"):
        gamut.create(str(tmp_path / "a.gamut"), writer="t", parameters={"x\x00y": "m"})
    with gamut.create(str(tmp_path / "b.gamut"), writer="t", labels={"case": "group"},
                       parameters={"x": "m"}) as s:
        with pytest.raises(gamut.GamutError, match="NUL"):
            s.add_run({"x": 1.0, "case": "bad\x00name"})
        s.add_run({"x": 1.0, "case": "good"})


def test_selections_outside_the_forms_are_refused(tmp_path):
    p = str(tmp_path / "t.gamut")
    with gamut.create(p, writer="t", parameters={"x": "m"}) as s:
        s.add_runs({"x": [1.0, 2.0, 3.0]})
    with gamut.open(p) as f:
        with pytest.raises(gamut.GamutError, match="integers"):
            f.get_parameter("x", rows=[0.9, 1.7])
        with pytest.raises(gamut.GamutError, match="integers"):
            f.get_parameter("x", rows=np.array([True, False, True]))
        assert f.get_parameter("x", rows=[]).size == 0
    c = str(tmp_path / "c.gamut")
    pts, cells = grid(2, 2)
    with gamut.create(c, writer="t", mesh="changing", per="run",
                       coordinates={"units": "m", "axes": 2}, parameters={"r": "m"},
                       fields={"q": {"units": "1", "at": "node"}}) as s:
        s.add_run({"r": 1.0}, fields={"q": np.zeros(4)}, points=pts, cells=cells)
    with gamut.open(c) as f:
        with pytest.raises(gamut.GamutError, match="one row at a time"):
            f.get_field("q", rows=slice(0, 1))
        with pytest.raises(gamut.GamutError, match="one run at a time"):
            f.get_cells()                         # one row, but no row given
        with pytest.raises(gamut.GamutError, match="integer"):
            f.get_cells(row=0.0)
        assert f.get_cells(row=0)[0].tolist() == [9]


def test_one_batch_cannot_give_a_member_two_geometries(tmp_path):
    p = str(tmp_path / "fam.gamut")
    pts, cells = grid(2, 2)
    with gamut.create(p, writer="t", mesh="shared", per="group:member",
                       coordinates={"units": "m", "axes": 2},
                       labels={"member": "group"}, parameters={"mach": "1"}) as s:
        s.set_mesh(cells=cells, n_nodes=4)
        with pytest.raises(gamut.GamutError, match="two different geometries"):
            s.add_runs({"member": ["a", "a"], "mach": [1.0, 2.0]}, points=[pts, pts * 2])
        s.add_runs({"member": ["a", "a"], "mach": [1.0, 2.0]}, points=[pts, pts.copy()])
    with gamut.open(p) as f:
        assert f.row_count == 2


def test_counts_that_overflow_are_refused(tmp_path):
    with gamut.create(str(tmp_path / "t.gamut"), writer="t", parameters={"x": "m"}) as s:
        h = s._handle()
        _lib.call("gamut_batch_begin", h, 1)
        one = np.zeros(1)
        with pytest.raises(gamut.GamutError, match="too large"):
            _lib.call("gamut_batch_values", h, b"x", _lib.GAMUT_FLOAT64,
                      one.ctypes.data_as(ctypes.c_void_p), (1 << 61) + 1)
        s.add_run({"x": 1.0})


def test_scattered_selections_read_by_gathering(tmp_path):
    # Many blocks (more than 64 index runs across the axes) are read as one
    # box and gathered; the result must equal the whole read, indexed.
    p = str(tmp_path / "g.gamut")
    rng = np.random.default_rng(3)
    with gamut.create(p, writer="t", mesh="shared", per="run",
                       coordinates={"units": "m", "axes": 3}, parameters={"k": "1"},
                       fields={"a": {"units": "1", "at": "node"}}) as s:
        s.set_mesh(n_nodes=300)
        s.add_runs({"k": np.arange(70.0)}, fields={"a": rng.normal(size=(70, 300))},
                   points=list(rng.normal(size=(70, 300, 3))))
    rows = np.sort(rng.choice(70, 40, replace=False))
    nodes = np.sort(rng.choice(300, 100, replace=False))
    with gamut.open(p) as f:
        whole = f.get_field("a")
        np.testing.assert_array_equal(f.get_field("a", rows=rows, nodes=nodes),
                                      whole[np.ix_(rows, nodes)])
        pts = np.stack([f.get_points(row=int(r)) for r in range(70)])
        h = f._handle()
        got = _lib.read(h, "coordinates", _lib.Selection(rows, "rows"),
                        _lib.Selection(nodes, "nodes"), np.dtype(np.float64))
        np.testing.assert_array_equal(got, pts[np.ix_(rows, nodes)])


# --- models, close, and caps on every file-sized buffer --------------------------------


class _Bad:
    """A model type whose numbers hold an illegal key below the top level."""
    type = "test_bad"

    def __init__(self, numbers):
        self.numbers = numbers

    @classmethod
    def load(cls, numbers):
        return cls(numbers)

    def save(self):
        return self.numbers

    def call(self, inputs, wanted):
        return {}


def _model_file(path):
    return gamut.create_model(path, writer="t",
                               parameters={"x": {"units": "1", "lower": 0.0, "upper": 1.0}},
                               scalars={"y": {"units": "1", "model": "m", "output": "y"}})


def test_refused_model_adds_nothing(tmp_path):
    p = str(tmp_path / "m.gamut")
    with _model_file(p) as mf:
        with pytest.raises(gamut.GamutError) as e:
            mf.add_model("m", _Bad({"v": 1.0, "w": np.arange(3), "zz": {"bad name": 1}}), ["x"])
        assert e.value.rule == "E8"
        mf.add_model("m", gamut.Nearest(["x"], [0.0], [1.0], [[0.5]], {"y": [2.0]}), ["x"])
    assert not gamut.validate(p).findings
    with gamut.evaluate(p, {"x": [0.1]}) as out:
        assert out.get_scalar("y").tolist() == [2.0]


def test_refused_close_keeps_the_file_open(tmp_path):
    p = str(tmp_path / "m.gamut")
    mf = _model_file(p)
    with pytest.raises(gamut.GamutError) as e:
        mf.close()
    assert e.value.rule == "E16"
    mf.add_model("m", gamut.Nearest(["x"], [0.0], [1.0], [[0.5]], {"y": [2.0]}), ["x"])
    mf.close()
    assert not gamut.validate(p).findings


def test_close_refused_inside_with_discards_the_file(tmp_path):
    p = str(tmp_path / "m.gamut")
    pts, cells = grid(2, 2)
    with pytest.raises(ZeroDivisionError):
        with gamut.create(p, writer="t", mesh="shared", per="fixed",
                           coordinates={"units": "m", "axes": 2}, parameters={"x": "m"}):
            1 / 0                    # leaves before set_mesh: the file cannot be finished
    assert not os.path.exists(p)


def test_refused_coordinate_declaration_changes_nothing(tmp_path):
    h = ctypes.c_void_p()
    p = str(tmp_path / "c.gamut")
    _lib.call("gamut_create", p.encode(), b"t", b"shared", b"fixed", ctypes.byref(h))
    try:
        with pytest.raises(gamut.GamutError):
            _lib.call("gamut_declare_coordinates", h, b"m", _lib.GAMUT_INT64, 2, b"", b"")
        _lib.call("gamut_declare_coordinates", h, b"m", _lib.GAMUT_FLOAT64, 2, b"", b"")
        pts = np.zeros((3, 2))
        _lib.call("gamut_geometry_begin", h)
        _lib.call("gamut_geometry_points", h, _lib.GAMUT_FLOAT64, pts.ctypes.data_as(ctypes.c_void_p), 3, 2)
        _lib.call("gamut_set_mesh", h)
    finally:
        _lib.call("gamut_close", h)
    assert not gamut.validate(p).findings


def test_trailing_nul_in_a_name_is_refused(tmp_path):
    with gamut.create(str(tmp_path / "t.gamut"), writer="t", labels={"case": "group"},
                       parameters={"x": "m"}) as s:
        with pytest.raises(gamut.GamutError, match="NUL"):
            s.add_run({"x": 1.0, "case": "a\x00"})
        with pytest.raises(gamut.GamutError, match="NUL"):
            s.add_runs({"x": [1.0], "case": ["b\x00\x00"]})
        s.add_run({"x": 1.0, "case": "a"})


def test_malformed_axes_leave_no_file(tmp_path):
    p = str(tmp_path / "a.gamut")
    with pytest.raises(gamut.GamutError) as e:
        gamut.create(p, writer="t", mesh="shared", per="fixed",
                      coordinates={"units": "m", "axes": "two"})
    assert e.value.rule == "E24" and not os.path.exists(p)


def test_as_given_float32_coordinates_refuse_float64_points(tmp_path):
    p = str(tmp_path / "c.gamut")
    with gamut.create(p, writer="t", mesh="changing", per="run",
                       coordinates={"units": "m", "axes": 2}, parameters={"r": "m"}) as s:
        s.add_run({"r": 1.0}, points=np.zeros((3, 2), np.float32))
        with pytest.raises(gamut.GamutError) as e:
            s.add_run({"r": 2.0}, points=np.full((3, 2), 0.1234567891234))
        assert e.value.rule == "E4"
        s.add_run({"r": 2.0}, points=np.zeros((3, 2), np.float32))
    with gamut.open(p) as f:
        assert f.row_count == 2


def test_cli_zone_on_a_changing_mesh_and_bad_rows(tmp_path, capsys):
    from gamut import cli
    p = str(tmp_path / "z.gamut")
    pts, cells = grid(2, 2)
    with gamut.create(p, writer="t", mesh="changing", per="run",
                       coordinates={"units": "m", "axes": 2}, parameters={"r": "m"},
                       mesh_labels={"zone": {"at": "node", "categories": ["x", "y"]}},
                       fields={"q": {"units": "1", "at": "node"}}) as s:
        s.add_run({"r": 1.0}, fields={"q": np.arange(4.0)}, points=pts, cells=cells,
                  mesh_labels={"zone": [0, 1, 1, 0]})
    out = str(tmp_path / "q.csv")
    assert cli.main(["get", p, "q", "--zone", "zone=y", "--rows", "0", "-o", out, "--json"]) == 0
    capsys.readouterr()
    assert cli.main(["get", p, "q", "--rows", "0,2,", "-o", out, "--json"]) != 0
    assert "--rows takes positions" in capsys.readouterr().out


def test_with_block_discards_a_file_its_close_refuses(tmp_path):
    p = str(tmp_path / "m.gamut")
    with pytest.raises(gamut.GamutError) as e:
        with gamut.create(p, writer="t", mesh="shared", per="fixed",
                           coordinates={"units": "m", "axes": 2}, parameters={"x": "m"}):
            pass                                            # set_mesh never called
    assert e.value.rule == "E2" and not os.path.exists(p)


def test_selection_messages_say_where_positions_start(tmp_path):
    p = str(tmp_path / "t.gamut")
    with gamut.create(p, writer="t", parameters={"x": "m"}) as s:
        s.add_runs({"x": [1.0, 2.0, 3.0]})
    with gamut.open(p) as f:
        with pytest.raises(gamut.GamutError, match="counting from 0"):
            f.get_parameter("x", rows=[5])


def test_a_member_given_its_geometry_again_is_accepted_when_unchanged(tmp_path):
    p = str(tmp_path / "fam.gamut")
    pts, cells = grid(2, 2)
    with gamut.create(p, writer="t", mesh="shared", per="group:member",
                       coordinates={"units": "m", "axes": 2},
                       labels={"member": "group"}, parameters={"mach": "1"}) as s:
        s.set_mesh(cells=cells, n_nodes=4)
        s.add_run({"member": "a", "mach": 1.0}, points=pts)
        s.add_run({"member": "a", "mach": 2.0}, points=pts)          # the same: accepted
        with pytest.raises(gamut.GamutError, match="other geometry"):
            s.add_run({"member": "a", "mach": 3.0}, points=pts * 2)
    with gamut.open(p, mode="a") as s:                               # after a reopen too
        s.add_run({"member": "a", "mach": 4.0}, points=pts)
        with pytest.raises(gamut.GamutError, match="other geometry"):
            s.add_run({"member": "a", "mach": 5.0}, points=pts + 1)
    with gamut.open(p) as f:
        assert f.row_count == 3
    assert not gamut.validate(p).findings


def test_one_row_of_a_column_is_a_number_in_every_kind_of_file(tmp_path):
    p = str(tmp_path / "c.gamut")
    pts, cells = grid(2, 2)
    with gamut.create(p, writer="t", mesh="changing", per="run",
                       coordinates={"units": "m", "axes": 2}, parameters={"r": "m"},
                       scalars={"y": "1"}) as s:
        s.add_run({"r": 1.0, "y": 2.0}, points=pts, cells=cells)
    with gamut.open(p) as f:
        assert np.ndim(f.get_scalar("y", rows=0)) == 0
        assert np.ndim(f.get_parameter("r", rows=0)) == 0
        assert f.get_scalar("y", rows=[0]).shape == (1,)

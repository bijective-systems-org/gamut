"""append, extract and write_copy: each kind of file,
the refusals, ids, tables merged by name, and identity kept on a rewrite."""

from __future__ import annotations

import os

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


def table(path, cases, xs):
    with gamut.create(path, writer="t", parameters={"x": "m"},
                       labels={"case": "categorical"}, scalars={"y": "1"}) as s:
        s.add_runs({"x": xs, "case": cases, "y": [2 * v for v in xs]})


def test_append_tables_merges_by_name_and_continues_ids(tmp_path):
    a, b = str(tmp_path / "a.gamut"), str(tmp_path / "b.gamut")
    table(a, ["p", "q"], [1.0, 2.0])
    table(b, ["r", "p", "r"], [3.0, 4.0, 5.0])
    with gamut.open(a, mode="a") as s:
        s.notes["kept"] = "yes"
    assert gamut.append(a, b) == 3
    with gamut.open(a) as f:
        assert f.row_count == 5
        assert f.get_row_ids().tolist() == [0, 1, 2, 3, 4]
        assert f.get_label("case").tolist() == ["p", "q", "r", "p", "r"]
        assert f.get_parameter("x").tolist() == [1.0, 2.0, 3.0, 4.0, 5.0]
        assert f.notes == {"kept": "yes"}
    assert not gamut.validate(a).findings


def test_append_refuses_other_declarations_and_changes_nothing(tmp_path):
    a, b, c = (str(tmp_path / n) for n in ("a.gamut", "b.gamut", "c.gamut"))
    table(a, ["p"], [1.0])
    with gamut.create(b, writer="t", parameters={"x": "cm"}, labels={"case": "categorical"},
                       scalars={"y": "1"}) as s:
        s.add_run({"x": 1.0, "case": "p", "y": 1.0})
    with pytest.raises(gamut.GamutError, match="parameter x") as e:
        gamut.append(a, b)
    assert e.value.path == "x"
    with gamut.create_model(c, writer="t", parameters={"x": {"units": "m", "lower": 0, "upper": 1}},
                             scalars={"y": {"units": "1", "model": "m", "output": "y"}}) as mf:
        mf.add_model("m", gamut.Nearest(["x"], [0.0], [1.0], [[0.5]], {"y": [1.0]}), ["x"])
    with pytest.raises(gamut.GamutError) as e:
        gamut.append(a, c)
    assert e.value.rule in ("E16", "")
    with pytest.raises(gamut.GamutError, match="one file"):
        gamut.append(a, a)
    with gamut.open(a) as f:
        assert f.row_count == 1
    assert not gamut.validate(a).findings


def test_append_refuses_an_invalid_source(tmp_path):
    import h5py
    a, b = str(tmp_path / "a.gamut"), str(tmp_path / "b.gamut")
    table(a, ["p"], [1.0])
    table(b, ["p"], [2.0])
    with h5py.File(b, "r+") as h:
        h["x"].attrs["units"] = np.bytes_(b"m//s")
    with pytest.raises(gamut.GamutError) as e:
        gamut.append(a, b)
    assert e.value.rule in ("E3", "E7") and "not copied" in str(e.value)


def shared(path, points, fields):
    pts, cells = grid(3, 2)
    with gamut.create(path, writer="t", mesh="shared", per="fixed",
                       coordinates={"units": "m", "axes": 2}, parameters={"m": "1"},
                       fields={"p": {"units": "Pa", "at": "node"}}) as s:
        s.set_mesh(points, cells)
        s.add_runs({"m": np.arange(len(fields), dtype=float)}, fields={"p": fields})


def test_append_shared_mesh_needs_the_same_geometry(tmp_path):
    pts, _ = grid(3, 2)
    a, b, c = (str(tmp_path / n) for n in ("a.gamut", "b.gamut", "c.gamut"))
    shared(a, pts, np.ones((2, 6)))
    shared(b, pts, np.full((3, 6), 2.0))
    shared(c, pts * 2, np.ones((1, 6)))
    assert gamut.append(a, b) == 3
    with pytest.raises(gamut.GamutError, match="coordinates"):
        gamut.append(a, c)
    with gamut.open(a) as f:
        assert f.row_count == 5
        np.testing.assert_array_equal(f.get_field("p")[2:], np.full((3, 6), 2.0))
    assert not gamut.validate(a).findings


def family(path, members, scale):
    pts, cells = grid(2, 2)
    with gamut.create(path, writer="t", mesh="shared", per="group:member",
                       coordinates={"units": "m", "axes": 2},
                       labels={"member": "group"}, parameters={"mach": "1"},
                       fields={"p": {"units": "Pa", "at": "node"}}) as s:
        s.set_mesh(cells=cells, n_nodes=4)
        s.add_runs({"member": members, "mach": np.arange(len(members), dtype=float)},
                   fields={"p": np.ones((len(members), 4))},
                   points=[pts * scale[m] for m in members])


def test_append_family_shares_member_geometry(tmp_path):
    scale = {"a": 1.0, "b": 2.0, "c": 3.0}
    a, b, c = (str(tmp_path / n) for n in ("a.gamut", "b.gamut", "c.gamut"))
    family(a, ["a", "b"], scale)
    family(b, ["b", "c", "c"], scale)
    family(c, ["a"], {"a": 9.0})
    assert gamut.append(a, b) == 3
    with gamut.open(a) as f:
        assert f.get_label("member").tolist() == ["a", "b", "b", "c", "c"]
        pts, _ = grid(2, 2)
        np.testing.assert_array_equal(f.get_points(row=3), pts * 3.0)
        np.testing.assert_array_equal(f.get_points(row=2), pts * 2.0)
    with pytest.raises(gamut.GamutError, match="other geometry") as e:
        gamut.append(a, c)
    assert e.value.path == "member"
    assert not gamut.validate(a).findings


def changing(path, sizes, start=0.0):
    with gamut.create(path, writer="t", mesh="changing", per="run",
                       coordinates={"units": "m", "axes": 2}, parameters={"r": "m"},
                       mesh_labels={"zone": {"at": "cell", "categories": ["in", "out"]}},
                       fields={"p": {"units": "Pa", "at": "node"}}) as s:
        for k, n in enumerate(sizes):
            pts, cells = grid(n, n)
            ncell = len(cells[0])
            s.add_run({"r": start + k}, fields={"p": np.arange(n * n) + 100.0 * k},
                      points=pts, cells=cells, mesh_labels={"zone": np.arange(ncell) % 2})


def test_append_and_extract_changing_mesh(tmp_path):
    a, b, e = (str(tmp_path / n) for n in ("a.gamut", "b.gamut", "e.gamut"))
    changing(a, [3, 2])
    changing(b, [4], start=10.0)
    assert gamut.append(a, b) == 1
    with gamut.open(a) as f:
        assert f.row_count == 3
        np.testing.assert_array_equal(f.get_field("p", rows=2), np.arange(16.0))
        assert f.get_points(row=2).shape == (16, 2)
        assert f.get_mesh_label("zone", row=2).tolist() == [0, 1, 0, 1, 0, 1, 0, 1, 0]
    assert not gamut.validate(a).findings
    gamut.extract(a, e, [0, 2])
    with gamut.open(a) as f, gamut.open(e) as g:
        assert g.row_count == 2 and g.get_row_ids().tolist() == [0, 2]
        for r_src, r_dst in ((0, 0), (2, 1)):
            np.testing.assert_array_equal(f.get_field("p", rows=r_src), g.get_field("p", rows=r_dst))
            for x, y in zip(f.get_cells(row=r_src), g.get_cells(row=r_dst)):
                np.testing.assert_array_equal(x, y)
    assert not gamut.validate(e).findings


def test_extract_keeps_ids_and_whole_tables(tmp_path):
    scale = {"a": 1.0, "b": 2.0, "c": 3.0}
    a, e = str(tmp_path / "a.gamut"), str(tmp_path / "e.gamut")
    family(a, ["a", "b", "c", "b"], scale)
    gamut.extract(a, e, slice(2, 4))
    with gamut.open(e) as g:
        assert g.get_row_ids().tolist() == [2, 3]
        assert g.get_label("member").tolist() == ["c", "b"]
        assert g.get_label_codes("member").tolist() == [2, 1]        # codes keep their meaning
        pts, _ = grid(2, 2)
        np.testing.assert_array_equal(g.get_points(row=0), pts * 3.0)
        np.testing.assert_array_equal(g.get_points(row=1), pts * 2.0)
    assert not gamut.validate(e).findings
    with gamut.open(e, mode="a") as s:                               # ids continue past the kept ones
        assert s.add_run({"member": "a", "mach": 9.0}, fields={"p": np.zeros(4)},
                         points=grid(2, 2)[0]) == 4


def test_write_copy_restores_the_layout_and_keeps_identity(tmp_path):
    import h5py
    a, c = str(tmp_path / "a.gamut"), str(tmp_path / "c.gamut")
    with gamut.create(a, writer="solver", parameters={"x": "m"}, scalars={"y": "1"},
                       title="grown") as s:
        s.add_run({"x": 0.0, "y": 0.0})
        s.notes["solver"] = "v2"
        s.set_private("log", b"\x00\x01raw")
    for k in range(1, 120):
        with gamut.open(a, mode="a") as s:
            s.add_run({"x": float(k), "y": 2.0 * k})
    # Another writer's layout: y rewritten in chunks larger than the default.
    with h5py.File(a, "r+") as h:
        data = h["y"][:]
        attrs = {k: h["y"].attrs[k] for k in h["y"].attrs if k != "DIMENSION_LIST"}
        h["y"].dims[0].detach_scale(h["row"])
        del h["y"]
        d = h.create_dataset("y", data=data, maxshape=(None,), chunks=(8192,),
                             compression="gzip", compression_opts=1, shuffle=True)
        for k, v in attrs.items():
            raw = v.encode() if isinstance(v, str) else v
            d.attrs.create(k, np.array(raw, dtype=h5py.string_dtype("utf-8", len(raw)))
                           if isinstance(raw, bytes) else raw)
        d.dims[0].attach_scale(h["row"])
    assert {f.rule for f in gamut.validate(a).findings} == {"W6"}
    gamut.write_copy(a, c)
    with gamut.open(a) as f, gamut.open(c) as g:
        assert f.describe()["file_id"] == g.describe()["file_id"]
        assert f.describe()["created"] == g.describe()["created"]
        assert g.describe()["writer"] == "solver" and g.describe()["title"] == "grown"
        np.testing.assert_array_equal(f.get_scalar("y"), g.get_scalar("y"))
        np.testing.assert_array_equal(f.get_row_ids(), g.get_row_ids())
        assert g.notes == {"solver": "v2"} and g.get_private("log") == b"\x00\x01raw"
    assert not gamut.validate(c).findings             # the default chunks again


def test_write_copy_of_a_model_file_evaluates_the_same(tmp_path):
    m, c = str(tmp_path / "m.gamut"), str(tmp_path / "c.gamut")
    with gamut.create_model(m, writer="t", parameters={"x": {"units": "1", "lower": 0, "upper": 1}},
                             scalars={"y": {"units": "1", "model": "fit", "output": "y"}}) as mf:
        mf.add_model("fit", gamut.Nearest(["x"], [0.0], [1.0], [[0.1], [0.9]], {"y": [1.0, 2.0]}),
                     ["x"])
    gamut.write_copy(m, c)
    with gamut.evaluate(m, {"x": [0.2, 0.8]}) as a, gamut.evaluate(c, {"x": [0.2, 0.8]}) as b:
        assert a.get_scalar("y").tolist() == b.get_scalar("y").tolist() == [1.0, 2.0]
    assert not gamut.validate(c).findings


def test_command_line_append_and_smaller_study(tmp_path, capsys):
    import json
    from gamut import cli
    a, b, s = (str(tmp_path / n) for n in ("a.gamut", "b.gamut", "s.gamut"))
    table(a, ["p", "q"], [1.0, 2.0])
    table(b, ["r"], [3.0])
    assert cli.main(["append", a, b, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["rows"] == 1
    assert cli.main(["get", a, "--where", "x > 1.5", "-o", s, "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"wrote": s, "rows": 2}
    with gamut.open(s) as f:
        assert f.get_row_ids().tolist() == [1, 2] and f.get_label("case").tolist() == ["q", "r"]
    assert cli.main(["get", a, "x", "-o", str(tmp_path / "t.gamut"), "--json"]) != 0


def zoned(path, categories, codes, rows=1):
    pts, cells = grid(3, 2)
    with gamut.create(path, writer="t", mesh="changing", per="run",
                       coordinates={"units": "m", "axes": 2}, parameters={"r": "m"},
                       mesh_labels={"zone": {"at": "cell", "categories": categories}}) as s:
        for k in range(rows):
            s.add_run({"r": float(k)}, points=pts, cells=cells,
                      mesh_labels={"zone": codes(k)})


def test_append_maps_mesh_labels_by_name(tmp_path):
    a, b = str(tmp_path / "a.gamut"), str(tmp_path / "b.gamut")
    zoned(a, ["in", "out"], lambda k: [0, 1])
    zoned(b, ["out", "in"], lambda k: [0, 0])               # both cells "out"
    gamut.append(a, b)
    with gamut.open(a) as f:
        assert f.get_mesh_label("zone", row=1).tolist() == [1, 1]   # "out" in a's table
    assert not gamut.validate(a).findings


def test_append_refuses_a_mesh_label_name_the_destination_lacks(tmp_path):
    from h5py import File
    a, b = str(tmp_path / "a.gamut"), str(tmp_path / "b.gamut")
    zoned(a, ["in", "out"], lambda k: [0, 1], rows=2)
    zoned(b, ["in", "out", "wall"], lambda k: [2, 2] if k >= 70 else [0, 1], rows=100)
    with File(a, "r") as h:
        before = h["mesh/coordinates"].shape
    with pytest.raises(gamut.GamutError, match="wall"):
        gamut.append(a, b)
    with gamut.open(a) as f:
        assert f.row_count == 2                             # nothing of the source
    with File(a, "r") as h:
        assert h["mesh/coordinates"].shape == before


def test_shared_mesh_labels_compare_by_name(tmp_path):
    pts, cells = grid(3, 2)

    def make(path, categories, codes):
        with gamut.create(path, writer="t", mesh="shared", per="fixed",
                           coordinates={"units": "m", "axes": 2}, parameters={"x": "1"},
                           mesh_labels={"zone": {"at": "cell", "categories": categories}}) as s:
            s.set_mesh(pts, cells, labels={"zone": codes})
            s.add_run({"x": 1.0})
    a, same, other = (str(tmp_path / n) for n in ("a.gamut", "s.gamut", "o.gamut"))
    make(a, ["in", "out"], [0, 1])
    make(same, ["out", "in"], [1, 0])                       # the same names
    make(other, ["out", "in"], [0, 1])                      # the opposite names
    assert gamut.append(a, same) == 1
    with pytest.raises(gamut.GamutError, match="mesh label"):
        gamut.append(a, other)


def test_validate_reports_a_missing_parameter(tmp_path):
    import h5py
    p = str(tmp_path / "t.gamut")
    table(p, ["p", "q", "r"], [1.0, 2.0, 3.0])
    with h5py.File(p, "r+") as h:
        h["x"][1] = np.nan
    assert "E5" in {f.rule for f in gamut.validate(p).findings}
    with pytest.raises(gamut.GamutError):
        gamut.append(str(tmp_path / "t.gamut"), p)


def test_nan_constants_are_equal_for_append(tmp_path):
    a, b = str(tmp_path / "a.gamut"), str(tmp_path / "b.gamut")
    for p in (a, b):
        with gamut.create(p, writer="t", parameters={"x": "m"},
                           constants={"c": (float("nan"), "1")}) as s:
            s.add_run({"x": 1.0})
    assert gamut.append(a, b) == 1


def test_cells_mismatch_is_refused_before_writing(tmp_path):
    a, b = str(tmp_path / "a.gamut"), str(tmp_path / "b.gamut")
    with gamut.create(a, writer="t", mesh="changing", per="run",
                       coordinates={"units": "m", "axes": 2}, parameters={"r": "m"}):
        pass                                                # closed with no rows and no cells
    pts, cells = grid(3, 2)
    with gamut.create(b, writer="t", mesh="changing", per="run",
                       coordinates={"units": "m", "axes": 2}, parameters={"r": "m"}) as s:
        s.add_run({"r": 1.0}, points=pts, cells=cells)
    with pytest.raises(gamut.GamutError, match="cells"):
        gamut.append(a, b)

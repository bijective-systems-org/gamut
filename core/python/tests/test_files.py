"""append, extract and write_copy (interface section 6): each kind of file,
the refusals, ids, tables merged by name, and identity kept on a rewrite."""

from __future__ import annotations

import os

import numpy as np
import pytest

import mestra


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
    with mestra.create(path, writer="t", parameters={"x": "m"},
                       labels={"case": "categorical"}, scalars={"y": "1"}) as s:
        s.add_runs({"x": xs, "case": cases, "y": [2 * v for v in xs]})


def test_append_tables_merges_by_name_and_continues_ids(tmp_path):
    a, b = str(tmp_path / "a.mes"), str(tmp_path / "b.mes")
    table(a, ["p", "q"], [1.0, 2.0])
    table(b, ["r", "p", "r"], [3.0, 4.0, 5.0])
    with mestra.open(a, mode="a") as s:
        s.notes["kept"] = "yes"
    assert mestra.append(a, b) == 3
    with mestra.open(a) as f:
        assert f.row_count == 5
        assert f.get_row_ids().tolist() == [0, 1, 2, 3, 4]
        assert f.get_label("case").tolist() == ["p", "q", "r", "p", "r"]
        assert f.get_parameter("x").tolist() == [1.0, 2.0, 3.0, 4.0, 5.0]
        assert f.notes == {"kept": "yes"}
    assert not mestra.validate(a).findings


def test_append_refuses_other_declarations_and_changes_nothing(tmp_path):
    a, b, c = (str(tmp_path / n) for n in ("a.mes", "b.mes", "c.mes"))
    table(a, ["p"], [1.0])
    with mestra.create(b, writer="t", parameters={"x": "cm"}, labels={"case": "categorical"},
                       scalars={"y": "1"}) as s:
        s.add_run({"x": 1.0, "case": "p", "y": 1.0})
    with pytest.raises(mestra.MestraError, match="parameter x") as e:
        mestra.append(a, b)
    assert e.value.path == "x"
    with mestra.create_model(c, writer="t", parameters={"x": {"units": "m", "lower": 0, "upper": 1}},
                             scalars={"y": {"units": "1", "model": "m", "output": "y"}}) as mf:
        mf.add_model("m", mestra.Nearest(["x"], [0.0], [1.0], [[0.5]], {"y": [1.0]}), ["x"])
    with pytest.raises(mestra.MestraError) as e:
        mestra.append(a, c)
    assert e.value.rule in ("E16", "")
    with pytest.raises(mestra.MestraError, match="one file"):
        mestra.append(a, a)
    with mestra.open(a) as f:
        assert f.row_count == 1
    assert not mestra.validate(a).findings


def test_append_refuses_an_invalid_source(tmp_path):
    import h5py
    a, b = str(tmp_path / "a.mes"), str(tmp_path / "b.mes")
    table(a, ["p"], [1.0])
    table(b, ["p"], [2.0])
    with h5py.File(b, "r+") as h:
        h["x"].attrs["units"] = np.bytes_(b"m//s")
    with pytest.raises(mestra.MestraError) as e:
        mestra.append(a, b)
    assert e.value.rule in ("E3", "E7") and "not copied" in str(e.value)


def shared(path, points, fields):
    pts, cells = grid(3, 2)
    with mestra.create(path, writer="t", mesh="shared", per="fixed",
                       coordinates={"units": "m", "axes": 2}, parameters={"m": "1"},
                       fields={"p": {"units": "Pa", "at": "node"}}) as s:
        s.set_mesh(points, cells)
        s.add_runs({"m": np.arange(len(fields), dtype=float)}, fields={"p": fields})


def test_append_shared_mesh_needs_the_same_geometry(tmp_path):
    pts, _ = grid(3, 2)
    a, b, c = (str(tmp_path / n) for n in ("a.mes", "b.mes", "c.mes"))
    shared(a, pts, np.ones((2, 6)))
    shared(b, pts, np.full((3, 6), 2.0))
    shared(c, pts * 2, np.ones((1, 6)))
    assert mestra.append(a, b) == 3
    with pytest.raises(mestra.MestraError, match="coordinates"):
        mestra.append(a, c)
    with mestra.open(a) as f:
        assert f.row_count == 5
        np.testing.assert_array_equal(f.get_field("p")[2:], np.full((3, 6), 2.0))
    assert not mestra.validate(a).findings


def family(path, members, scale):
    pts, cells = grid(2, 2)
    with mestra.create(path, writer="t", mesh="shared", per="group:member",
                       coordinates={"units": "m", "axes": 2},
                       labels={"member": "group"}, parameters={"mach": "1"},
                       fields={"p": {"units": "Pa", "at": "node"}}) as s:
        s.set_mesh(cells=cells, n_nodes=4)
        s.add_runs({"member": members, "mach": np.arange(len(members), dtype=float)},
                   fields={"p": np.ones((len(members), 4))},
                   points=[pts * scale[m] for m in members])


def test_append_family_shares_member_geometry(tmp_path):
    scale = {"a": 1.0, "b": 2.0, "c": 3.0}
    a, b, c = (str(tmp_path / n) for n in ("a.mes", "b.mes", "c.mes"))
    family(a, ["a", "b"], scale)
    family(b, ["b", "c", "c"], scale)
    family(c, ["a"], {"a": 9.0})
    assert mestra.append(a, b) == 3
    with mestra.open(a) as f:
        assert f.get_label("member").tolist() == ["a", "b", "b", "c", "c"]
        pts, _ = grid(2, 2)
        np.testing.assert_array_equal(f.get_points(row=3), pts * 3.0)
        np.testing.assert_array_equal(f.get_points(row=2), pts * 2.0)
    with pytest.raises(mestra.MestraError, match="other geometry") as e:
        mestra.append(a, c)
    assert e.value.path == "member"
    assert not mestra.validate(a).findings


def changing(path, sizes, start=0.0):
    with mestra.create(path, writer="t", mesh="changing", per="run",
                       coordinates={"units": "m", "axes": 2}, parameters={"r": "m"},
                       mesh_labels={"zone": {"at": "cell", "categories": ["in", "out"]}},
                       fields={"p": {"units": "Pa", "at": "node"}}) as s:
        for k, n in enumerate(sizes):
            pts, cells = grid(n, n)
            ncell = len(cells[0])
            s.add_run({"r": start + k}, fields={"p": np.arange(n * n) + 100.0 * k},
                      points=pts, cells=cells, mesh_labels={"zone": np.arange(ncell) % 2})


def test_append_and_extract_changing_mesh(tmp_path):
    a, b, e = (str(tmp_path / n) for n in ("a.mes", "b.mes", "e.mes"))
    changing(a, [3, 2])
    changing(b, [4], start=10.0)
    assert mestra.append(a, b) == 1
    with mestra.open(a) as f:
        assert f.row_count == 3
        np.testing.assert_array_equal(f.get_field("p", rows=2), np.arange(16.0))
        assert f.get_points(row=2).shape == (16, 2)
        assert f.get_mesh_label("zone", row=2).tolist() == [0, 1, 0, 1, 0, 1, 0, 1, 0]
    assert not mestra.validate(a).findings
    mestra.extract(a, e, [0, 2])
    with mestra.open(a) as f, mestra.open(e) as g:
        assert g.row_count == 2 and g.get_row_ids().tolist() == [0, 2]
        for r_src, r_dst in ((0, 0), (2, 1)):
            np.testing.assert_array_equal(f.get_field("p", rows=r_src), g.get_field("p", rows=r_dst))
            for x, y in zip(f.get_cells(row=r_src), g.get_cells(row=r_dst)):
                np.testing.assert_array_equal(x, y)
    assert not mestra.validate(e).findings


def test_extract_keeps_ids_and_whole_tables(tmp_path):
    scale = {"a": 1.0, "b": 2.0, "c": 3.0}
    a, e = str(tmp_path / "a.mes"), str(tmp_path / "e.mes")
    family(a, ["a", "b", "c", "b"], scale)
    mestra.extract(a, e, slice(2, 4))
    with mestra.open(e) as g:
        assert g.get_row_ids().tolist() == [2, 3]
        assert g.get_label("member").tolist() == ["c", "b"]
        assert g.get_label_codes("member").tolist() == [2, 1]        # codes keep their meaning
        pts, _ = grid(2, 2)
        np.testing.assert_array_equal(g.get_points(row=0), pts * 3.0)
        np.testing.assert_array_equal(g.get_points(row=1), pts * 2.0)
    assert not mestra.validate(e).findings
    with mestra.open(e, mode="a") as s:                               # ids continue past the kept ones
        assert s.add_run({"member": "a", "mach": 9.0}, fields={"p": np.zeros(4)},
                         points=grid(2, 2)[0]) == 4


def test_write_copy_restores_the_layout_and_keeps_identity(tmp_path):
    import h5py
    a, c = str(tmp_path / "a.mes"), str(tmp_path / "c.mes")
    with mestra.create(a, writer="solver", parameters={"x": "m"}, scalars={"y": "1"},
                       title="grown") as s:
        s.add_run({"x": 0.0, "y": 0.0})
        s.notes["solver"] = "v2"
        s.set_private("log", b"\x00\x01raw")
    for k in range(1, 120):
        with mestra.open(a, mode="a") as s:
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
    assert {f.rule for f in mestra.validate(a).findings} == {"W6"}
    mestra.write_copy(a, c)
    with mestra.open(a) as f, mestra.open(c) as g:
        assert f.describe()["file_id"] == g.describe()["file_id"]
        assert f.describe()["created"] == g.describe()["created"]
        assert g.describe()["writer"] == "solver" and g.describe()["title"] == "grown"
        np.testing.assert_array_equal(f.get_scalar("y"), g.get_scalar("y"))
        np.testing.assert_array_equal(f.get_row_ids(), g.get_row_ids())
        assert g.notes == {"solver": "v2"} and g.get_private("log") == b"\x00\x01raw"
    assert not mestra.validate(c).findings             # the default chunks again


def test_write_copy_of_a_model_file_evaluates_the_same(tmp_path):
    m, c = str(tmp_path / "m.mes"), str(tmp_path / "c.mes")
    with mestra.create_model(m, writer="t", parameters={"x": {"units": "1", "lower": 0, "upper": 1}},
                             scalars={"y": {"units": "1", "model": "fit", "output": "y"}}) as mf:
        mf.add_model("fit", mestra.Nearest(["x"], [0.0], [1.0], [[0.1], [0.9]], {"y": [1.0, 2.0]}),
                     ["x"])
    mestra.write_copy(m, c)
    with mestra.evaluate(m, {"x": [0.2, 0.8]}) as a, mestra.evaluate(c, {"x": [0.2, 0.8]}) as b:
        assert a.get_scalar("y").tolist() == b.get_scalar("y").tolist() == [1.0, 2.0]
    assert not mestra.validate(c).findings


def test_command_line_append_and_smaller_study(tmp_path, capsys):
    import json
    from mestra import cli
    a, b, s = (str(tmp_path / n) for n in ("a.mes", "b.mes", "s.mes"))
    table(a, ["p", "q"], [1.0, 2.0])
    table(b, ["r"], [3.0])
    assert cli.main(["append", a, b, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["rows"] == 1
    assert cli.main(["get", a, "--where", "x > 1.5", "-o", s, "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"wrote": s, "rows": 2}
    with mestra.open(s) as f:
        assert f.get_row_ids().tolist() == [1, 2] and f.get_label("case").tolist() == ["q", "r"]
    assert cli.main(["get", a, "x", "-o", str(tmp_path / "t.mes"), "--json"]) != 0

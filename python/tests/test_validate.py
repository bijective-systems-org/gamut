"""The validator through the core: files the library writes are clean, and
each rule fires on a file broken to break it (edited with h5py)."""

from __future__ import annotations

import shutil

import numpy as np
import pytest

import gamut

h5py = pytest.importorskip("h5py")


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


@pytest.fixture
def table(tmp_path):
    p = str(tmp_path / "table.gamut")
    with gamut.create(p, writer="t",
                       parameters={"mach": {"units": "1", "role": "condition", "lower": 0.0, "upper": 1.0},
                                   "t": {"units": "s", "role": "time", "run_group": "run"}},
                       labels={"run": "group", "split": {"role": "split", "categories": ["train", "test"]}},
                       scalars={"cl": "1", "cl_std": {"units": "1", "of": "cl", "statistic": "std"}},
                       generalisation_group="run") as s:
        s.add_runs({"mach": [0.1, 0.2, 0.3, 0.4], "t": [0.0, 1.0, 0.0, 1.0],
                    "run": ["a", "a", "b", "b"], "split": ["train", "train", "test", "test"],
                    "cl": [0.1, 0.2, 0.3, 0.4], "cl_std": [0.01, 0.01, 0.01, 0.01]})
    return p


@pytest.fixture
def shared(tmp_path):
    p = str(tmp_path / "shared.gamut")
    pts, cells = grid(3, 3)
    with gamut.create(p, writer="t", mesh="shared", per="fixed",
                       coordinates={"units": "m", "axes": 2}, parameters={"k": "1"},
                       mesh_labels={"zone": {"at": "cell", "categories": ["in", "out"]}},
                       fields={"p": {"units": "Pa", "at": "node"},
                               "u": {"units": "m s-1", "at": "cell", "vector": "vel", "axis": "x"},
                               "v": {"units": "m s-1", "at": "cell", "vector": "vel", "axis": "y"}}) as s:
        s.set_mesh(pts, cells, labels={"zone": [0, 0, 1, 1]})
        s.add_runs({"k": [1.0, 2.0]}, fields={"p": np.ones((2, 9)), "u": np.ones((2, 4)),
                                              "v": np.ones((2, 4))})
    return p


def clean(path):
    r = gamut.validate(path)
    assert r.findings == (), [f"{f.rule} {f.path}: {f.message}" for f in r.findings]


def test_files_the_library_writes_are_clean(table, shared, tmp_path):
    clean(table)
    clean(shared)
    # The other kinds.
    pts, cells = grid(3, 3)
    fam = str(tmp_path / "fam.gamut")
    with gamut.create(fam, writer="t", mesh="shared", per="group:member",
                       coordinates={"units": "m", "axes": 2}, labels={"member": "group"},
                       parameters={"k": "1"}, fields={"p": {"units": "Pa", "at": "node"}}) as s:
        s.set_mesh(cells=cells, n_nodes=9)
        s.add_runs({"member": ["b", "a", "b"], "k": [1.0, 2.0, 3.0]}, fields={"p": np.zeros((3, 9))},
                   points=[pts, pts * 2, pts])
    clean(fam)
    ch = str(tmp_path / "ch.gamut")
    with gamut.create(ch, writer="t", mesh="changing", per="run",
                       coordinates={"units": "m", "axes": 2}, parameters={"k": "1"},
                       fields={"p": {"units": "Pa", "at": "node"}}) as s:
        s.add_run({"k": 1.0}, fields={"p": np.zeros(9)}, points=pts, cells=cells)
        p2, c2 = grid(2, 2)
        s.add_run({"k": 2.0}, fields={"p": np.zeros(4)}, points=p2, cells=c2)
    clean(ch)
    with gamut.open(ch, mode="a") as s:
        s.add_run({"k": 3.0}, fields={"p": np.zeros(4)}, points=p2, cells=c2)
    clean(ch)


def broken(path, tmp_path, edit):
    q = str(tmp_path / "broken.gamut")
    shutil.copy(path, q)
    with h5py.File(q, "r+") as f:
        edit(f)
    return gamut.validate(q)


def fires(report, rule, path=None):
    hits = [f for f in report.findings if f.rule == rule and (path is None or f.path == path)]
    assert hits, f"{rule} did not fire; findings: " + "; ".join(
        f"{f.rule} {f.path}: {f.message}" for f in report.findings)


@pytest.mark.parametrize("rule, edit", [
    ("E1", lambda f: f.attrs.modify("format", np.bytes_(b"gamut/9"))),
    ("E2", lambda f: f.attrs.__delitem__("file_id")),
    ("E3", lambda f: (f["mach"].attrs.__delitem__("lower"), f["mach"].attrs.create("lower", 0, dtype="i8"))),
    ("E7", lambda f: (f["mach"].attrs.__delitem__("units"),
                      f["mach"].attrs.create("units", np.bytes_(b"m//s")))),
    ("E7", lambda f: f["cl"].attrs.__delitem__("units")),
    ("E9", lambda f: f["split"].__setitem__(0, 5)),
    ("E12", lambda f: f["cl_std"].attrs.modify("of", np.bytes_(b"nothing"))),
    ("E14", lambda f: f["row"].__setitem__(1, 0)),
    ("E15", lambda f: f["t"].attrs.modify("run_group", np.bytes_(b"split"))),
    ("E16", lambda f: f["cl"].attrs.create("model", np.bytes_(b"m"))),
    ("E16", lambda f: (f["mach"].attrs.modify("lower", 2.0))),
    ("E22", lambda f: f.__setitem__("alias", h5py.SoftLink("/cl"))),
    ("E22", lambda f: f.__setitem__("ext", h5py.ExternalLink("other.h5", "/x"))),
    ("W1", lambda f: f["split"].__setitem__(1, 1)),
    ("W3", lambda f: f["cl"].__setitem__(2, np.nan)),
    ("W4", lambda f: f["mach"].__setitem__(0, 5.0)),
    ("W5", lambda f: f["cl"].attrs.create("colour", np.bytes_(b"blue"))),
    ("W5", lambda f: f["cl"].attrs.modify("role", np.bytes_(b"future-role"))),
    ("W8", lambda f: f.attrs.modify("created", np.bytes_(b"yesterday"))),
    ("W9", lambda f: f["t"].__setitem__(1, 0.0)),
    ("W10", lambda f: f["cl_std"].__setitem__(0, -1.0)),
])
def test_rules_fire_on_a_broken_table(table, tmp_path, rule, edit):
    fires(broken(table, tmp_path, edit), rule)


@pytest.mark.parametrize("rule, edit", [
    ("E4", lambda f: (f["mesh/node_fields"].__delitem__("p"),
                      f["mesh/node_fields"].create_dataset("p", data=np.zeros((2, 9), dtype="i4")))),
    ("E6", lambda f: f["mesh"].attrs.modify("kind", np.bytes_(b"wobbly"))),
    ("E10", lambda f: f["mesh/cell_connectivity"].__setitem__(0, 99)),
    ("E11", lambda f: f["mesh"].attrs.modify("support_id", np.bytes_(b"0" * 64))),
    ("E13", lambda f: f["mesh/cell_fields/v"].attrs.modify("axis", np.bytes_(b"x"))),
    ("E13", lambda f: f["mesh/cell_fields/v"].attrs.modify("axis", np.bytes_(b"z"))),
    ("E9", lambda f: f["mesh/cell_labels/zone"].__setitem__(0, 7)),
    ("E16", lambda f: f["mesh/coordinates"].attrs.create("model", np.bytes_(b"shape"))),
])
def test_rules_fire_on_a_broken_mesh(shared, tmp_path, rule, edit):
    fires(broken(shared, tmp_path, edit), rule)


def test_values_past_the_validators_limit_are_reported_unchecked(table, tmp_path):
    # Every row-long dataset grown past 2**26 rows without writing: the
    # file stays small, and the checks that read values say they did not.
    def grow(f):
        n = (1 << 26) + 1
        for name, obj in f.items():
            if isinstance(obj, h5py.Dataset) and obj.maxshape[:1] == (None,):
                obj.resize((n,) + obj.shape[1:])
    warned = {f.path for f in broken(table, tmp_path, grow).warnings if f.rule == "W11"}
    assert {"row", "mach", "cl", "split", "t"} <= warned


def test_missing_values_are_located(tmp_path):
    p = str(tmp_path / "gaps.gamut")
    pts, cells = grid(3, 3)
    pressure = np.ones((2, 9))
    pressure[1, 4] = np.nan
    with gamut.create(p, writer="t", mesh="shared", per="fixed",
                       coordinates={"units": "m", "axes": 2}, parameters={"k": "1"},
                       scalars={"cl": "1"}, fields={"p": {"units": "Pa", "at": "node"}}) as s:
        s.set_mesh(pts, cells)
        s.add_runs({"k": [1.0, 2.0], "cl": [np.nan, np.nan]}, fields={"p": pressure})
    found = {f.path: f.message for f in gamut.validate(p).warnings if f.rule == "W3"}
    assert found["cl"] == "2 values are missing or not finite, the first at row 0"
    assert found["node_fields/p"] == "1 value is missing or not finite, the first at row 1, node 4"
    # On a changing mesh, by the row's own node.
    p = str(tmp_path / "gaps_changing.gamut")
    small, cells_small = grid(2, 3)
    with gamut.create(p, writer="t", mesh="changing", per="run",
                       coordinates={"units": "m", "axes": 2}, parameters={"k": "1"},
                       fields={"p": {"units": "Pa", "at": "node"}}) as s:
        s.add_run({"k": 1.0}, points=pts, cells=cells, fields={"p": np.ones(9)})
        s.add_run({"k": 2.0}, points=small, cells=cells_small,
                  fields={"p": np.array([1.0, 1.0, 1.0, np.nan, 1.0, 1.0])})
    found = {f.path: f.message for f in gamut.validate(p).warnings if f.rule == "W3"}
    assert found["node_fields/p"] == "1 value is missing or not finite, the first at row 1, node 3"



def test_statuses_and_split_groups_are_named(tmp_path):
    # W2 counts each status a row is not converged with, and says so when no
    # status is named converged; W1 names the first group a split divides.
    p = str(tmp_path / "named.gamut")
    with gamut.create(p, writer="t", parameters={"x": "1"},
                       labels={"geometry": "group", "split": {"role": "split", "categories": ["train", "test"]},
                               "status": {"role": "status", "categories": ["yes", "no"]}},
                       generalisation_group="geometry") as s:
        s.add_runs({"x": [0.0, 1.0, 2.0, 3.0], "geometry": ["A", "A", "B", "B"],
                    "split": ["train", "train", "train", "test"], "status": ["yes", "no", "no", "yes"]})
    found = {f.rule: f.message for f in gamut.validate(p).warnings}
    assert found["W2"] == ("4 rows are not converged (2 yes, 2 no), the first row 0; no status is "
                           "named converged, the one name that marks a row as usable")
    assert found["W1"] == 'the split places rows of one geometry on both sides: "B" (row 3)'


def test_meshes_larger_than_a_block_are_checked_whole(tmp_path):
    # The cell checks read 65,536 entries at a time; a defect in a later
    # block is found as one in the first is.
    import h5py
    pts, cells = grid(301, 301)                       # 90,000 quads, 360,000 entries
    path = str(tmp_path / "big.gamut")
    with gamut.create(path, writer="t", mesh="shared", per="fixed",
                       coordinates={"units": "m", "axes": 2}, parameters={"k": "1"}) as s:
        s.set_mesh(pts, cells)
        s.add_run({"k": 1.0})
    clean(path)
    for edit, rule in ((lambda f: f["mesh/cell_connectivity"].__setitem__(300_000, 10**6), "E10"),
                       (lambda f: f["mesh/cell_offsets"].__setitem__(70_000, 3), "E10")):
        broken = str(tmp_path / "broken.gamut")
        shutil.copy(path, broken)
        with h5py.File(broken, "r+") as f:
            edit(f)
        assert rule in {x.rule for x in gamut.validate(broken).errors}

    # A changing mesh: a node number valid for the file but not for its
    # instance, in the second instance, past the first block.
    small, cells_small = grid(201, 201)
    path = str(tmp_path / "changing.gamut")
    with gamut.create(path, writer="t", mesh="changing", per="run",
                       coordinates={"units": "m", "axes": 2}, parameters={"k": "1"}) as s:
        s.add_run({"k": 1.0}, points=pts, cells=cells)
        s.add_run({"k": 2.0}, points=small, cells=cells_small)
    clean(path)
    with h5py.File(path, "r+") as f:
        f["mesh/cell_connectivity"][360_000 + 100_000] = len(small) + 5
    errors = gamut.validate(path).errors
    assert [x.rule for x in errors] == ["E10"] and "outside its instance" in errors[0].message


def test_a_name_used_twice(shared, tmp_path):
    def edit(f):
        f["mesh/cell_fields/u"].attrs.modify("vector", np.bytes_(b"vel"))
        f.copy(f["mesh/node_fields/p"], "/mesh/cell_labels/p")
    fires(broken(shared, tmp_path, edit), "E8")


def test_storage_rules(table, tmp_path):
    def unchunked(f):
        data = f["cl"][:]
        attrs = dict(f["cl"].attrs)
        del f["cl"]
        d = f.create_dataset("cl", data=data, maxshape=(None,), chunks=(4,), compression="lzf")
        for k, v in attrs.items():
            if k not in ("DIMENSION_LIST",):
                d.attrs[k] = v
        d.dims[0].attach_scale(f["row"])
    fires(broken(table, tmp_path, unchunked), "E20")


def test_unreadable_file_is_one_finding(tmp_path):
    p = tmp_path / "not.gamut"
    p.write_bytes(b"not an hdf5 file")
    r = gamut.validate(str(p))
    assert r.error_ids == ["E1"] and len(r.findings) == 1


# --- rules the 2.0 pass made the validator check (#99, #100, #110) ---------

def _rules(p):
    return {f.rule for f in gamut.validate(p).findings}


def _model(p):
    with gamut.create_model(p, writer="t", parameters={"x": {"units": "1", "lower": 0, "upper": 1}},
                            scalars={"y": {"units": "1", "model": "fit", "output": "y"}}) as mf:
        mf.add_model("fit", gamut.Nearest(["x"], [0.0], [1.0], [[0.1], [0.9]], {"y": [1.0, 2.0]}),
                     ["x"])


def _sweep(p, mesh=False):
    pts, cells = grid(3, 2)
    with gamut.create(p, writer="t", parameters={"mach": "1"}, scalars={"cl": "1"},
                      labels={"status": {"role": "status", "categories": ["converged", "failed"]}},
                      **({"mesh": "shared", "per": "fixed", "coordinates": {"units": "m", "axes": 2},
                          "fields": {"p": {"units": "Pa", "at": "node"}}} if mesh else {})) as s:
        if mesh:
            s.set_mesh(pts, cells)
        s.add_runs({"mach": [0.3, 0.4], "cl": [0.1, 0.2], "status": ["converged", "converged"]},
                   **({"fields": {"p": np.ones((2, 6))}} if mesh else {}))
    assert not gamut.validate(p).findings


def test_model_data_needs_its_scales_and_its_widths(tmp_path):
    a, b_ = str(tmp_path / "a.gamut"), str(tmp_path / "b.gamut")
    _model(a), _model(b_)
    with h5py.File(a, "r+") as f:
        f["models/fit"].create_dataset("extra", data=np.arange(3.0))
    with h5py.File(b_, "r+") as f:
        f["models/fit"].attrs.create("k", np.int32(3))
    assert "E19" in _rules(a)
    assert "E18" in _rules(b_)


def test_a_string_attribute_is_sized_to_its_bytes(tmp_path):
    p = str(tmp_path / "t.gamut")
    _sweep(p)
    with h5py.File(p, "r+") as f:
        del f["cl"].attrs["units"]
        f["cl"].attrs.create("units", np.array(b"1", dtype=h5py.string_dtype("utf-8", 8)))
    assert _rules(p) == {"E3"}


def test_a_derivative_along_an_axis_the_coordinates_lack_is_e13(tmp_path):
    p = str(tmp_path / "m.gamut")
    pts, cells = grid(3, 2)
    with gamut.create(p, writer="t", mesh="shared", per="fixed", coordinates={"units": "m", "axes": 2},
                      parameters={"mach": "1"}, scalars={"s": "1"},
                      fields={"ds": {"units": "m-1", "at": "node", "of": "s",
                                     "with_respect_to": "coordinates", "axis": "x"}}) as s:
        s.set_mesh(pts, cells)
        s.add_run({"mach": 0.3, "s": 1.0}, fields={"ds": np.zeros(6)})
    assert not gamut.validate(p).findings
    with h5py.File(p, "r+") as f:
        d = f["mesh/node_fields/ds"]
        del d.attrs["axis"]
        d.attrs.create("axis", np.array(b"z", dtype=h5py.string_dtype("utf-8", 1)))
    assert _rules(p) == {"E13"}


def test_an_unknown_statistic_still_has_its_vector_and_axis_checked(tmp_path):
    p = str(tmp_path / "t.gamut")
    _sweep(p)
    with h5py.File(p, "r+") as f:
        for k, v in (("of", b"cl"), ("statistic", b"skew"), ("axis", b"q")):
            f["cl"].attrs.create(k, np.array(v, dtype=h5py.string_dtype("utf-8", len(v))))
    assert _rules(p) == {"W5", "E13"}


@pytest.mark.parametrize("units", ["m s", "m s", "m　s", "m s"])
def test_a_space_outside_ascii_does_not_parse_in_units(units):
    from gamut import _lib
    assert _lib.units_valid("m s") and not _lib.units_valid(units)
    assert _lib.units_valid("µm") and _lib.units_valid("Å")


def test_absent_required_objects_are_e2(tmp_path):
    def broken(name, edit, mesh=False):
        p = str(tmp_path / f"{name}.gamut")
        _sweep(p, mesh=mesh)
        with h5py.File(p, "r+") as f:
            edit(f)
        return _rules(p)
    assert "E2" in broken("category", lambda f: f["status"].attrs.__delitem__("category"))
    assert "E2" in broken("kind", lambda f: f["mesh"].attrs.__delitem__("kind"), mesh=True)
    assert "E2" in broken("support", lambda f: f["mesh"].attrs.__delitem__("support_id"), mesh=True)
    rules = broken("offsets", lambda f: f.__delitem__("mesh/cell_offsets"), mesh=True)
    assert "E2" in rules and "E4" not in rules


def test_a_fixed_layout_is_valid_and_read_only_until_rewritten(tmp_path):
    p, grow = str(tmp_path / "fixed.gamut"), str(tmp_path / "grow.gamut")
    _sweep(p)
    with h5py.File(p, "r+") as f:
        cols = ["mach", "cl", "status"]
        saved = {}
        for n in cols:
            saved[n] = (f[n][:], [(k, f[n].attrs[k], f[n].attrs.get_id(k).dtype)
                                  for k in f[n].attrs if k != "DIMENSION_LIST"])
            f[n].dims[0].detach_scale(f["row"])
            del f[n]
        ids = f["row"][:]
        row_attrs = [(k, f["row"].attrs[k], f["row"].attrs.get_id(k).dtype)
                     for k in f["row"].attrs if k not in ("CLASS", "NAME", "REFERENCE_LIST")]
        del f["row"]
        r = f.create_dataset("row", data=ids, track_order=True)
        r.make_scale("row")
        for k, v, t in row_attrs:
            r.attrs.create(k, v, dtype=t)
        for n, (data, attrs) in saved.items():
            d = f.create_dataset(n, data=data)
            for k, v, t in attrs:
                d.attrs.create(k, v, dtype=t)
            d.dims[0].attach_scale(f["row"])
    assert not gamut.validate(p).findings
    with pytest.raises(gamut.GamutError, match="this file is read-only; write_copy makes a copy") as e:
        with gamut.open(p, mode="a") as s:
            s.add_run({"mach": 0.5, "cl": 0.3, "status": "converged"})
    assert e.value.rule == "E25"                  # valid and read-only, not E20's bad storage
    gamut.write_copy(p, grow)
    with gamut.open(grow, mode="a") as s:
        s.add_run({"mach": 0.5, "cl": 0.3, "status": "converged"})
    assert not gamut.validate(grow).findings


def test_a_fixed_table_makes_the_file_read_only_before_anything_changes(tmp_path):
    p = str(tmp_path / "t.gamut")
    _sweep(p)
    with h5py.File(p, "r+") as f:                       # the table fixed, its scale left unlimited
        t = f["categories/status"]
        data, attrs = t[...], [(k, t.attrs[k], t.attrs.get_id(k).dtype)
                               for k in t.attrs if k != "DIMENSION_LIST"]
        dtype = t.dtype
        t.dims[0].detach_scale(f["category_status"])
        del f["categories/status"]
        n = f.create_dataset("categories/status", data=data, dtype=dtype)
        for k, v, ty in attrs:
            n.attrs.create(k, v, dtype=ty)
        n.dims[0].attach_scale(f["category_status"])
    assert not gamut.validate(p).findings
    before = open(p, "rb").read()
    with pytest.raises(gamut.GamutError, match="read-only"):
        gamut.open(p, mode="a")
    assert open(p, "rb").read() == before


def test_absent_cell_arrays_are_e2_without_a_cascade(tmp_path):
    p = str(tmp_path / "s.gamut")
    _sweep(p, mesh=True)
    with h5py.File(p, "r+") as f:
        del f["mesh/cell_types"]
    rules = _rules(p)
    assert "E2" in rules and not rules & {"E5", "E11"}, rules
    q = str(tmp_path / "c.gamut")
    pts, cells = grid(3, 2)
    with gamut.create(q, writer="t", mesh="changing", per="run", coordinates={"units": "m", "axes": 2},
                      parameters={"r": "m"}) as s:
        s.add_run({"r": 1.0}, points=pts, cells=cells)
    with h5py.File(q, "r+") as f:
        del f["mesh/cell_offsets"]
    rules = _rules(q)
    assert "E2" in rules and "E21" not in rules, rules


def test_an_empty_attribute_is_not_an_absent_one(tmp_path):
    def emptied(name, obj, attr, mesh=False):
        p = str(tmp_path / f"{name}.gamut")
        _sweep(p, mesh=mesh)
        with h5py.File(p, "r+") as f:
            del f[obj].attrs[attr]
            f[obj].attrs.create(attr, np.array(b"", dtype=h5py.string_dtype("utf-8", 1)))
        return _rules(p)
    assert "E9" in emptied("category", "status", "category") and "E2" not in emptied("c2", "status", "category")
    assert "E6" in emptied("kind", "mesh", "kind", mesh=True)
    rules = emptied("support", "mesh", "support_id", mesh=True)
    assert "E11" in rules and "E2" not in rules


def _changing_file(p):
    pts, cells = grid(3, 2)
    with gamut.create(p, writer="t", mesh="changing", per="run", coordinates={"units": "m", "axes": 2},
                      parameters={"r": "m"}) as s:
        s.add_run({"r": 1.0}, points=pts, cells=cells)
    return pts, cells


def test_a_fixed_value_scale_makes_the_file_read_only_before_anything_changes(tmp_path):
    p = str(tmp_path / "c.gamut")
    _changing_file(p)                       # no node fields: nothing uses node_value
    with h5py.File(p, "r+") as f:
        old = f["mesh/node_value"]
        n, attrs = old.shape[0], {k: old.attrs[k] for k in old.attrs if k not in ("CLASS", "NAME")}
        del f["mesh/node_value"]
        d = f["mesh"].create_dataset("node_value", shape=(n,), dtype=">f4", track_order=True)
        d.make_scale("This is a netCDF dimension but not a netCDF variable.%10d" % n)
        for k, v in attrs.items():
            d.attrs[k] = v
    assert not gamut.validate(p).findings
    before = open(p, "rb").read()
    with pytest.raises(gamut.GamutError, match="read-only"):
        gamut.open(p, mode="a")
    assert open(p, "rb").read() == before


def test_an_ignored_dataset_named_like_a_scale_does_not_make_a_file_read_only(tmp_path):
    p = str(tmp_path / "c.gamut")
    pts, cells = _changing_file(p)
    with h5py.File(p, "r+") as f:
        f["mesh/row"] = np.zeros(1)         # fixed, named like the row scale; nothing grows it
    with gamut.open(p, mode="a") as s:
        s.add_run({"r": 2.0}, points=pts, cells=cells)
    assert not [x for x in gamut.validate(p).findings if x.severity == "error"]


@pytest.mark.parametrize("kind", ["int", "ints", "text", "vlen-uint64", "two-lists"])
def test_a_dimension_list_of_another_type_is_e19_not_a_crash(tmp_path, kind):
    p = str(tmp_path / "t.gamut")
    _sweep(p)
    with h5py.File(p, "r+") as f:      # HDF5's own scale calls would follow it as references
        del f["cl"].attrs["DIMENSION_LIST"]
        if kind == "int":
            f["cl"].attrs["DIMENSION_LIST"] = np.int64(0)
        elif kind == "ints":
            f["cl"].attrs["DIMENSION_LIST"] = np.arange(3, dtype=np.int32)
        elif kind == "text":
            f["cl"].attrs["DIMENSION_LIST"] = "x" * 100
        elif kind == "vlen-uint64":
            lists = np.empty(1, dtype=object)
            lists[0] = np.array([7], np.uint64)
            f["cl"].attrs.create("DIMENSION_LIST", lists, dtype=h5py.vlen_dtype(np.uint64))
        else:                           # references, but one list too many for one axis
            refs = np.empty(2, dtype=object)
            refs[0] = np.array([f["row"].ref], dtype=h5py.ref_dtype)
            refs[1] = np.array([f["row"].ref], dtype=h5py.ref_dtype)
            f["cl"].attrs.create("DIMENSION_LIST", refs, dtype=h5py.vlen_dtype(h5py.ref_dtype))
    assert "E19" in _rules(p)
    with gamut.open(p) as s:
        s.get_parameter("mach")


def test_the_scale_attached_is_checked_not_a_namesake(tmp_path):
    p = str(tmp_path / "m.gamut")
    with gamut.create_model(p, writer="t", parameters={"x": {"units": "1", "lower": 0, "upper": 1}},
                            scalars={"y": {"units": "1", "model": "fit", "output": "y"}}) as mf:
        mf.add_model("fit", gamut.Nearest(["x"], [0.0], [1.0], [[0.1], [0.9]], {"y": [1.0, 2.0]}),
                     ["x"])
    name = "This is a netCDF dimension but not a netCDF variable.%10d"
    with h5py.File(p, "r+") as f:
        g = f["models/fit"]
        d = g.create_dataset("extra", data=np.arange(3.0))
        local = g.create_dataset("gamut_extra_d0", shape=(3,), dtype=">f4", track_order=True)
        local.make_scale(name % 3)
        other = f["private"].create_group("b") if "private" in f else f.create_group("private/b")
        far = other.create_dataset("gamut_extra_d0", shape=(2,), dtype=">f4", track_order=True)
        far.make_scale(name % 2)
        d.dims[0].attach_scale(far)            # the attached scale is two long, the namesake three
    messages = [x.message for x in gamut.validate(p).findings if x.rule == "E19"]
    assert any("attached to a scale named gamut_extra_d0 that is not models/fit/gamut_extra_d0" in m
               for m in messages), messages


def test_a_scale_of_the_right_name_elsewhere_is_not_the_scale(tmp_path):
    p = str(tmp_path / "t.gamut")
    _sweep(p)
    with h5py.File(p, "r+") as f:
        decoy = f.require_group("private").create_dataset("row", data=np.arange(2, dtype="<i8"))
        decoy.make_scale("row")
        f["cl"].dims[0].detach_scale(f["row"])
        f["cl"].dims[0].attach_scale(decoy)
    messages = [x.message for x in gamut.validate(p).findings if x.rule == "E19"]
    assert any("is attached to a scale named row that is not row" in m for m in messages), messages


def test_widening_a_table_whose_dimension_list_is_wrong_is_refused_not_a_crash(tmp_path):
    p = str(tmp_path / "t.gamut")
    with gamut.create(p, writer="t", parameters={"x": "1"}, labels={"case": "group"}) as s:
        s.add_run({"x": 1.0, "case": "a"})
    with h5py.File(p, "r+") as f:
        del f["categories/case"].attrs["DIMENSION_LIST"]
        f["categories/case"].attrs["DIMENSION_LIST"] = np.int64(0)
    with pytest.raises(gamut.GamutError) as e:
        with gamut.open(p, mode="a") as s:
            s.add_run({"x": 2.0, "case": "a name long enough to widen the table"})
    assert e.value.rule == "E19"

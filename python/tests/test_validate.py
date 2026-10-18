"""The validator through the core: files the library writes are clean, and
each rule fires on a file broken to break it (edited with h5py)."""

from __future__ import annotations

import shutil

import numpy as np
import pytest

import mestra

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
    p = str(tmp_path / "table.mes")
    with mestra.create(p, writer="t",
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
    p = str(tmp_path / "shared.mes")
    pts, cells = grid(3, 3)
    with mestra.create(p, writer="t", mesh="shared", per="fixed",
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
    r = mestra.validate(path)
    assert r.findings == (), [f"{f.rule} {f.path}: {f.message}" for f in r.findings]


def test_files_the_library_writes_are_clean(table, shared, tmp_path):
    clean(table)
    clean(shared)
    # The other kinds.
    pts, cells = grid(3, 3)
    fam = str(tmp_path / "fam.mes")
    with mestra.create(fam, writer="t", mesh="shared", per="group:member",
                       coordinates={"units": "m", "axes": 2}, labels={"member": "group"},
                       parameters={"k": "1"}, fields={"p": {"units": "Pa", "at": "node"}}) as s:
        s.set_mesh(cells=cells, n_nodes=9)
        s.add_runs({"member": ["b", "a", "b"], "k": [1.0, 2.0, 3.0]}, fields={"p": np.zeros((3, 9))},
                   points=[pts, pts * 2, pts])
    clean(fam)
    ch = str(tmp_path / "ch.mes")
    with mestra.create(ch, writer="t", mesh="changing", per="run",
                       coordinates={"units": "m", "axes": 2}, parameters={"k": "1"},
                       fields={"p": {"units": "Pa", "at": "node"}}) as s:
        s.add_run({"k": 1.0}, fields={"p": np.zeros(9)}, points=pts, cells=cells)
        p2, c2 = grid(2, 2)
        s.add_run({"k": 2.0}, fields={"p": np.zeros(4)}, points=p2, cells=c2)
    clean(ch)
    with mestra.open(ch, mode="a") as s:
        s.add_run({"k": 3.0}, fields={"p": np.zeros(4)}, points=p2, cells=c2)
    clean(ch)


def broken(path, tmp_path, edit):
    q = str(tmp_path / "broken.mes")
    shutil.copy(path, q)
    with h5py.File(q, "r+") as f:
        edit(f)
    return mestra.validate(q)


def fires(report, rule, path=None):
    hits = [f for f in report.findings if f.rule == rule and (path is None or f.path == path)]
    assert hits, f"{rule} did not fire; findings: " + "; ".join(
        f"{f.rule} {f.path}: {f.message}" for f in report.findings)


@pytest.mark.parametrize("rule, edit", [
    ("E1", lambda f: f.attrs.modify("format", np.bytes_(b"mestra/9"))),
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
])
def test_rules_fire_on_a_broken_mesh(shared, tmp_path, rule, edit):
    fires(broken(shared, tmp_path, edit), rule)


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
    p = tmp_path / "not.mes"
    p.write_bytes(b"not an hdf5 file")
    r = mestra.validate(str(p))
    assert r.error_ids == ["E1"] and len(r.findings) == 1

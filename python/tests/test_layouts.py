"""Every layout through the writer and back: each kind of mesh, each `per`,
with and without cells, float32 coordinates, written in batches, appended
to after a reopen, extracted, rewritten, and appended to another copy.
Every file stays valid, and every copy holds the values it came from."""

from __future__ import annotations

import numpy as np
import pytest

import gamut


def grid(nx, ny, scale=1.0):
    xs, ys = np.meshgrid(np.arange(nx, dtype=float), np.arange(ny, dtype=float))
    pts = np.stack([xs.ravel(), ys.ravel()], axis=1) * scale
    conn = []
    for j in range(ny - 1):
        for i in range(nx - 1):
            a = j * nx + i
            conn += [a, a + 1, a + nx + 1, a + nx]
    n = (nx - 1) * (ny - 1)
    return pts, (np.full(n, 9, np.uint8), np.arange(0, 4 * n + 1, 4), np.array(conn))


LAYOUTS = ["table", "shared_fixed", "shared_fixed_cloud", "shared_run", "shared_run_float32",
           "shared_group", "changing_run", "changing_run_cloud", "changing_group"]


def declare(layout, path):
    kw = dict(writer="layouts", parameters={"x": "1"}, scalars={"y": "1"},
              labels={"status": {"role": "status", "categories": ["converged", "failed"]}})
    if layout == "table":
        return gamut.create(path, **kw)
    cells = not layout.endswith("cloud")
    kind, per = ("shared" if layout.startswith("shared") else "changing"), "run"
    if layout.startswith("shared_fixed"):
        per = "fixed"
    if layout.endswith("group"):
        per = "group:member"
        kw["labels"]["member"] = "group"
    fields = {"p": {"units": "Pa", "at": "node"}}
    if cells:
        fields["t"] = {"units": "K", "at": "cell"}
    kw.update(mesh=kind, per=per, coordinates={"units": "m", "axes": 2}, fields=fields)
    if cells:
        kw["mesh_labels"] = {"zone": {"at": "cell", "categories": ["a", "b"]}}
    if layout.endswith("float32"):
        kw["precision"] = {"coordinates": "float32"}
    return gamut.create(path, **kw)


def runs(layout, start, count):
    """`count` runs from run number `start`: columns, fields, geometry."""
    cells = not layout.endswith("cloud")
    ids = range(start, start + count)
    cols = {"x": [float(i) for i in ids], "y": [10.0 * i for i in ids],
            "status": ["converged" for i in ids]}
    if layout.endswith("group"):
        cols["member"] = ["m%d" % (i % 2) for i in ids]
    if layout == "table":
        return cols, {}, None
    if layout.startswith("shared"):
        pts, cl = grid(3, 2)
        fields = {"p": np.array([np.arange(6.0) + 100 * i for i in ids])}
        if cells:
            fields["t"] = np.array([np.arange(2.0) + 1000 * i for i in ids])
        geometry = None
        if layout.startswith("shared_run"):
            geometry = {"points": [pts * (1 + i) for i in ids]}
        if layout == "shared_group":
            geometry = {"points": [pts * (1 + i % 2) for i in ids]}
        return cols, fields, geometry
    # Changing: each run (or member) its own grid.
    shapes = [(3, 2) if (i % 2 == 0) else (4, 3) for i in ids]
    grids = [grid(nx, ny, 1 + (i % 2)) for (nx, ny), i in zip(shapes, ids)]
    fields = {"p": np.concatenate([np.arange(len(g[0]), dtype=float) + 100 * i
                                   for g, i in zip(grids, ids)])}
    geometry = {"points": [g[0] for g in grids]}
    if cells:
        fields["t"] = np.concatenate([np.arange(len(g[1][0]), dtype=float) + 1000 * i
                                      for g, i in zip(grids, ids)])
        geometry["cells"] = [g[1] for g in grids]
        geometry["mesh_labels"] = [{"zone": np.arange(len(g[1][0])) % 2} for g in grids]
    return cols, fields, geometry


def write_runs(study, layout, start, count):
    cols, fields, geometry = runs(layout, start, count)
    study.add_runs(cols, fields=fields or None, **(geometry or {}))


def set_mesh(study, layout):
    if layout == "table" or layout.startswith("changing"):
        return
    pts, cl = grid(3, 2)
    labels = None if layout.endswith("cloud") else {"zone": np.array([0, 1])}
    cells = None if layout.endswith("cloud") else cl
    if layout.startswith("shared_fixed"):
        study.set_mesh(pts, cells, labels=labels)
    else:
        study.set_mesh(cells=cells, labels=labels, n_nodes=6)


def values(path):
    """Every row's values, row by row, keyed by name."""
    out = {}
    with gamut.open(path) as f:
        for name in ("x", "y"):
            out[name] = f.get_parameter(name).tolist() if name == "x" else f.get_scalar(name).tolist()
        out["status"] = list(f.get_label("status"))
        for name in f.names("node_fields") + f.names("cell_fields"):
            out[name] = [f.get_field(name, rows=r).tolist() for r in range(f.row_count)]
        if f.type != "table":
            out["points"] = [f.get_points(row=r).tolist() if f.describe("coordinates")["per"] != "fixed"
                             else f.get_points().tolist() for r in range(f.row_count)]
    return out


def clean(path):
    findings = gamut.validate(path).findings
    assert not findings, [(x.rule, x.path, x.message) for x in findings]


@pytest.mark.parametrize("layout", LAYOUTS)
def test_a_layout_survives_every_writer(tmp_path, layout):
    p = str(tmp_path / "study.gamut")
    with declare(layout, p) as s:
        set_mesh(s, layout)
        write_runs(s, layout, 0, 2)
        write_runs(s, layout, 2, 1)
    clean(p)
    with gamut.open(p, mode="a") as s:
        write_runs(s, layout, 3, 1)
    clean(p)
    whole = values(p)
    assert whole["x"] == [0.0, 1.0, 2.0, 3.0]

    part = str(tmp_path / "part.gamut")
    gamut.extract(p, part, [0, 2])
    clean(part)
    got = values(part)
    for name, rows in whole.items():
        assert got[name] == [rows[0], rows[2]], name

    copy = str(tmp_path / "copy.gamut")
    gamut.write_copy(p, copy)
    clean(copy)
    assert values(copy) == whole

    gamut.append(copy, p)
    errors = [x for x in gamut.validate(copy).findings if x.severity == "error"]
    assert not errors, [(x.rule, x.path, x.message) for x in errors]
    doubled = values(copy)
    for name, rows in whole.items():
        assert doubled[name] == rows + rows, name

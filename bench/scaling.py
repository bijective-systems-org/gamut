"""How Gamut's writes and reads scale, for the three kinds of study.

    python bench/scaling.py WORK_DIR OUT.json

A run table of 10,000 to 1,000,000 rows; one shared mesh, from 100 runs of
10,000 nodes to 100 runs of 100,000 and 1,000 runs of 10,000; and a mesh
per run, up to 100 runs of about 20,000 nodes. Each study is written, then
read the common ways (a column, a selection, scattered rows, the whole
field, one run, a strip of nodes, every run's field in turn) and
validated. Reads are the median of a few repeats in this process. Set
GAMUT_LIBRARY to time a particular build of the core, and compare two by
running this once for each, alternating, on a quiet machine. The studies
it writes in WORK_DIR are removed at the end.
"""
import json
import os
import statistics
import sys
import time

import numpy as np

import gamut


def best(f, repeat=3):
    out = []
    for _ in range(repeat):
        t = time.perf_counter()
        f()
        out.append(time.perf_counter() - t)
    return statistics.median(out)


def once(f):
    t = time.perf_counter()
    f()
    return time.perf_counter() - t


def grid(n):
    xs = np.linspace(0, 1, n)
    pts = np.array([(x, y) for y in xs for x in xs])
    quads = [(j * n + i, j * n + i + 1, (j + 1) * n + i + 1, (j + 1) * n + i)
             for j in range(n - 1) for i in range(n - 1)]
    conn = np.array(quads).ravel()
    return pts, ([9] * len(quads), np.arange(0, len(conn) + 1, 4), conn)


def table(d, rows):
    p = os.path.join(d, f"table-{rows}.gamut")
    rng = np.random.default_rng(rows)
    cols = {"x": rng.random(rows), "mach": rng.random(rows),
            "status": np.where(rng.random(rows) < 0.9, "converged", "failed"),
            "cl": rng.random(rows), "cd": rng.random(rows), "cm": rng.random(rows)}

    def write():
        if os.path.exists(p):
            os.remove(p)
        with gamut.create(p, writer="scaling", parameters={"x": "1", "mach": "1"},
                          labels={"status": {"role": "status",
                                             "categories": ["converged", "failed"]}},
                          scalars={"cl": "1", "cd": "1", "cm": "1"}) as s:
            for k in range(0, rows, 100000):
                s.add_runs({n: v[k:k + 100000] for n, v in cols.items()})
    out = {"write": once(write)}
    picks = np.sort(np.random.default_rng(1).choice(rows, 100, replace=False))
    out["open"] = best(lambda: gamut.open(p).close(), 5)
    with gamut.open(p) as s:
        out["read a column"] = best(lambda: s.get_scalar("cl"))
        out["select"] = best(lambda: s.select("x > 0.5 and status == converged"))
        out["100 scattered rows"] = best(lambda: s.get_scalar("cl", rows=picks))
        out["one row x100"] = best(lambda: [s.get_scalar("cl", rows=7) for _ in range(100)])
        out["table()"] = best(lambda: s.table())
    out["validate"] = once(lambda: gamut.validate(p))
    return out


def shared(d, runs, nodes):
    p = os.path.join(d, f"shared-{runs}x{nodes}.gamut")
    n = int(round(nodes ** 0.5))
    pts, cells = grid(n)
    base = np.sin(pts[:, 0] * 7) * np.cos(pts[:, 1] * 5)

    def write():
        if os.path.exists(p):
            os.remove(p)
        with gamut.create(p, writer="scaling", mesh="shared", per="fixed",
                          parameters={"alpha": "degree"},
                          coordinates={"units": "m", "axes": 2}, scalars={"cl": "1"},
                          fields={"p": {"units": "Pa", "at": "node"}}) as s:
            s.set_mesh(pts, cells)
            for i in range(runs):
                s.add_run({"alpha": float(i), "cl": 0.01 * i}, fields={"p": base * (1 + 1e-3 * i)})
    out = {"write": once(write)}
    with gamut.open(p) as s:
        out["read the field"] = best(lambda: s.get_field("p"))
        out["one run"] = best(lambda: s.get_field("p", rows=runs // 2), 5)
        out["100 nodes, every run"] = best(lambda: s.get_field("p", nodes=slice(0, 100)))
        out["10 scattered runs"] = best(lambda: s.get_field("p", rows=list(range(1, runs, runs // 10))[:10]))
    with gamut.open(p, threads=4) as s:
        out["read the field, 4 threads"] = best(lambda: s.get_field("p"))
    out["validate"] = once(lambda: gamut.validate(p))
    return out


def changing(d, runs, nodes):
    p = os.path.join(d, f"changing-{runs}x{nodes}.gamut")
    sizes = [int(round((nodes * (0.8 + 0.4 * i / max(runs - 1, 1))) ** 0.5)) for i in range(runs)]
    meshes = {n: grid(n) for n in set(sizes)}

    def write():
        if os.path.exists(p):
            os.remove(p)
        with gamut.create(p, writer="scaling", mesh="changing", per="run",
                          parameters={"refine": "1"},
                          coordinates={"units": "m", "axes": 2}, scalars={"cl": "1"},
                          fields={"p": {"units": "Pa", "at": "node"}}) as s:
            for i, n in enumerate(sizes):
                pts, cells = meshes[n]
                s.add_run({"refine": float(n), "cl": 0.01 * i},
                          fields={"p": np.sin(pts[:, 0] * 7) * (1 + 1e-3 * i)},
                          points=pts, cells=cells)
    out = {"write": once(write)}
    with gamut.open(p) as s:
        out["every run's field, one at a time"] = best(
            lambda: [s.get_field("p", rows=r) for r in range(runs)])
        out["one run's mesh"] = best(lambda: (s.get_points(row=runs // 2),
                                              s.get_cells(row=runs // 2)), 5)
        out["one run's field"] = best(lambda: s.get_field("p", rows=runs // 2), 5)
    out["validate"] = once(lambda: gamut.validate(p))
    return out


if __name__ == "__main__":
    d, dest = sys.argv[1], sys.argv[2]
    os.makedirs(d, exist_ok=True)
    result = {}
    for rows in (10_000, 100_000, 1_000_000):
        result[f"table {rows} rows"] = table(d, rows)
    for runs, nodes in ((100, 10_000), (100, 100_000), (1000, 10_000)):
        result[f"shared mesh {runs} runs x {nodes} nodes"] = shared(d, runs, nodes)
    for runs, nodes in ((20, 5_000), (100, 5_000), (100, 20_000)):
        result[f"mesh per run, {runs} runs x ~{nodes} nodes"] = changing(d, runs, nodes)
    for name in os.listdir(d):   # the studies written here, nothing else
        if name.startswith(("table-", "shared-", "changing-")) and name.endswith(".gamut"):
            os.remove(os.path.join(d, name))
    with open(dest, "w") as fh:
        json.dump({"library": os.environ.get("GAMUT_LIBRARY"), "seconds": result}, fh, indent=1)

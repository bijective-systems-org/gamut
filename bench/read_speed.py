"""Read and write speed of the core on a study shaped like the scale study's
large case: 128 runs of 262,144 nodes, five float32 fields per run.

    GAMUT_LIBRARY=build-release/libgamut.dylib \\
        python bench/read_speed.py /path/to/scratch [--keep]

Prints one JSON document.  Reads are warm (the file is in the page cache
after writing); cold reads need the cache evicted, which this script does
not do.
"""

from __future__ import annotations

import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))
import gamut  # noqa: E402

RUNS, NODES, FIELDS = 128, 262_144, ("p", "t", "u", "v", "w")


def field(run: int, k: int, x: np.ndarray) -> np.ndarray:
    """A smooth field with a little noise, like a solver's output."""
    rng = np.random.default_rng(run * 10 + k)
    base = np.sin(x * (1 + k) + run * 0.05) * (1 + 0.01 * run)
    return (base + rng.normal(0, 1e-3, x.size)).astype(np.float32)


def timed(fn, repeat=5):
    best = float("inf")
    out = None
    for _ in range(repeat):
        t0 = time.perf_counter()
        out = fn()
        best = min(best, time.perf_counter() - t0)
    return best, out


def main() -> None:
    scratch = sys.argv[1]
    keep = "--keep" in sys.argv
    path = os.path.join(scratch, "bench_shared.gamut")
    x = np.linspace(0, 20, NODES)
    pts = np.stack([x, np.zeros(NODES), np.zeros(NODES)], axis=1)
    t0 = time.perf_counter()
    with gamut.create(path, writer="bench", mesh="shared", per="fixed",
                       coordinates={"units": "m", "axes": 3},
                       parameters={"mach": {"units": "1", "role": "condition"}},
                       fields={f: {"units": "1", "at": "node"} for f in FIELDS}) as s:
        s.set_mesh(pts)
        for start in range(0, RUNS, 8):
            runs = range(start, start + 8)
            s.add_runs({"mach": [0.3 + 0.004 * r for r in runs]},
                       fields={f: np.stack([field(r, k, x) for r in runs])
                               for k, f in enumerate(FIELDS)})
    write_s = time.perf_counter() - t0
    size = os.path.getsize(path)
    raw = RUNS * NODES * len(FIELDS) * 4

    result = {"runs": RUNS, "nodes": NODES, "fields": len(FIELDS),
              "raw_bytes": raw, "file_bytes": size, "write_s": round(write_s, 3)}
    with gamut.open(path) as f:
        one, _ = timed(lambda: [f.get_field(n, rows=64) for n in FIELDS])
        region = slice(100_000, 100_000 + NODES // 100)
        reg, _ = timed(lambda: [f.get_field(n, nodes=region) for n in FIELDS])
        full, arr = timed(lambda: f.get_field("p"), repeat=3)
        result.update({
            "one_run_all_fields_ms": round(one * 1000, 2),
            "one_percent_of_every_run_all_fields_ms": round(reg * 1000, 2),
            "one_field_every_run_s": round(full, 3),
            "one_field_every_run_MB_per_s": round(arr.nbytes / full / 1e6, 1),
        })
    try:
        import h5py
        with h5py.File(path, "r") as h:
            d = h["/mesh/node_fields/p"]
            hfull, _ = timed(lambda: d[:], repeat=3)
            hone, _ = timed(lambda: [h[f"/mesh/node_fields/{n}"][64] for n in FIELDS])
            result["h5py_one_field_every_run_s"] = round(hfull, 3)
            result["h5py_one_run_all_fields_ms"] = round(hone * 1000, 2)
            result["chunk"] = list(d.chunks)
    except ImportError:
        pass
    if not keep:
        os.remove(path)
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()

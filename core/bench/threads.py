"""Field reads with 1, 2, 4 and 8 decompression threads on a file written
by read_speed.py --keep.  Warm reads, best of three.

    MESTRA_LIBRARY=core/build-release/libmestra.dylib python core/bench/threads.py FILE
"""
import json, os, sys, time
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))
import mestra

def best(fn, n=3):
    b = float("inf")
    for _ in range(n):
        t0 = time.perf_counter(); out = fn(); b = min(b, time.perf_counter() - t0)
    return b, out

path = sys.argv[1]
fields = ("p", "t", "u", "v", "w")
rows = []
for threads in (1, 2, 4, 8):
    with mestra.open(path, threads=threads) as f:
        full, arr = best(lambda: f.get_field("p"))
        allf, _ = best(lambda: [f.get_field(n) for n in fields], 2)
        reg, _ = best(lambda: [f.get_field(n, nodes=slice(100_000, 102_621)) for n in fields])
        one, _ = best(lambda: [f.get_field(n, rows=64) for n in fields])
        rows.append({"threads": threads,
                     "one_field_every_run_s": round(full, 3),
                     "one_field_every_run_MB_per_s": round(arr.nbytes / full / 1e6),
                     "five_fields_every_run_s": round(allf, 3),
                     "one_percent_every_run_five_fields_ms": round(reg * 1000, 1),
                     "one_run_five_fields_ms": round(one * 1000, 2)})
print(json.dumps(rows, indent=1))

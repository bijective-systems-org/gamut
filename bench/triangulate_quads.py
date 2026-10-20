"""Prepare the common benchmark payload with two triangles per quad.

python bench/triangulate_quads.py SOURCE.gamut OUTPUT.gamut > preparation.json

No nodes or nodal results are interpolated. This changes connectivity, not
the solver results; nonplanar quads need not describe the same surface.
Run every peer on OUTPUT.gamut, never just PMSH on the transformed mesh.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from shared_mesh import load, write_gamut


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source", type=Path)
    ap.add_argument("output", type=Path)
    args = ap.parse_args()
    if args.source.resolve() == args.output.resolve():
        ap.error("source and output must be different files")
    data = load(str(args.source))
    types, offsets, connectivity = data["cells"]
    if not np.all(types == 9):
        raise ValueError("the source must contain only VTK_QUAD cells")
    quads = connectivity.reshape(-1, 4)
    triangles = quads[:, ((0, 1, 2), (0, 2, 3))].reshape(-1, 3)
    data["cells"] = (np.full(len(triangles), 5, dtype=types.dtype),
                     np.arange(len(triangles) + 1, dtype=offsets.dtype) * 3,
                     triangles.reshape(-1))
    write_gamut(data, str(args.output))
    other = load(str(args.output))
    np.testing.assert_equal(other["member"], data["member"])
    for key in ("fields", "table"):
        for name, values in data[key].items():
            np.testing.assert_equal(other[key][name], values)
    for key in ("points", "cells"):
        for got, expected in zip(other[key], data[key], strict=True):
            np.testing.assert_equal(got, expected)
    print(json.dumps({
        "source": args.source.name,
        "source_sha256": hashlib.sha256(args.source.read_bytes()).hexdigest(),
        "output": args.output.name,
        "output_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
        "transform": "quad [a,b,c,d] -> triangles [a,b,c], [a,c,d] in source-cell order",
        "source_cells": len(quads), "output_cells": len(triangles),
        "output_vtk_type": 5, "verified": True,
        "payload": "benchmark nodes, nodal fields, run table and geometry mapping; no cell results",
    }, indent=1))


if __name__ == "__main__":
    main()

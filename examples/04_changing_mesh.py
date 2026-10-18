"""Runs on different meshes: a refinement study.

The same flow on three meshes of increasing resolution. Each run keeps its
own mesh; reads take one run at a time, and comparing runs node by node is
left to tools that build a correspondence first.
"""
import numpy as np

import mestra
from _cylinder import pressure, ring

with mestra.create("refinement.mes", writer="example refinement", mesh="changing", per="run",
                   coordinates={"units": "m", "axes": 2},
                   parameters={"cells_round": {"units": "1", "role": "design"}},
                   scalars={"cp_min": "1"},
                   fields={"cp": {"units": "1", "at": "node"}}) as study:
    for n in (24, 48, 96):
        points, cells, t, r = ring(n_theta=n, n_r=n // 4)
        cp = pressure(t, r)
        study.add_run({"cells_round": n, "cp_min": cp.min()}, fields={"cp": cp},
                      points=points, cells=cells)

with mestra.open("refinement.mes") as study:
    for row in range(study.row_count):
        types, offsets, connectivity = study.get_cells(row=row)
        print(f"row {row}: {len(study.get_points(row=row))} nodes, {len(types)} cells, "
              f"cp_min {study.get_scalar('cp_min', rows=row):.3f}")

"""Runs on different meshes: a refinement study.

The same flow on three meshes of increasing resolution, with the pressure
stored per cell as a finite-volume solver reports it. Each run keeps its
own mesh; reads take one run at a time. The lowest cell value approaches
the exact -3 as the cells next to the wall shrink. The MATLAB, Julia and
C++ examples refinement are the same program and print the same lines.
"""
import numpy as np

import gamut
from _cylinder import pressure, ring

with gamut.create("refinement.gamut", writer="example refinement", mesh="changing", per="run",
                   coordinates={"units": "m", "axes": 2},
                   parameters={"cells_round": {"units": "1", "role": "design"}},
                   scalars={"cp_min": "1"},
                   fields={"cp": {"units": "1", "at": "cell"}}) as study:
    for n in (24, 48, 96):
        points, cells, _, _ = ring(n_theta=n, n_r=n // 4)
        centres = points[cells[2].reshape(-1, 4)].mean(axis=1)        # four nodes per quad
        cp = pressure(np.arctan2(centres[:, 1], centres[:, 0]), np.hypot(*centres.T))
        study.add_run({"cells_round": n, "cp_min": cp.min()}, fields={"cp": cp},
                      points=points, cells=cells)

with gamut.open("refinement.gamut") as study:
    rounds = study.get_parameter("cells_round")
    for row in range(study.row_count):
        types, offsets, connectivity = study.get_cells(row=row)
        cp = study.get_field("cp", rows=row)
        print(f"{rounds[row]:g} cells round: {len(study.get_points(row=row))} nodes, {len(types)} cells, "
              f"lowest cell cp {cp.min():.3f}")

"""The README's example: a sweep written run by run, then read by condition.

Potential flow past a cylinder at nine values of circulation, on one mesh
that every run shares. The MATLAB, Julia and C examples ask the same file
the same question and print the same numbers.
"""
import numpy as np

import gamut
from _cylinder import pressure, ring

points, cells, t, r = ring()

with gamut.create("cylinder.gamut", writer="my sweep", mesh="shared", per="fixed",
                   coordinates={"units": "m", "axes": 2},
                   parameters={"gamma": {"units": "m2 s-1", "role": "design"}},
                   fields={"cp": {"units": "1", "at": "node"}}) as study:
    study.set_mesh(points, cells)                          # once: every run shares it
    for gamma in np.linspace(0.0, 4.0, 9):                 # one run at a time, as a solver finishes
        study.add_run({"gamma": gamma}, fields={"cp": pressure(t, r, gamma=gamma)})

with gamut.open("cylinder.gamut") as study:
    rows = study.select("gamma > 2")
    cp = study.get_field("cp", rows=rows, nodes=[12])     # runs x nodes
    print("cp on top of the cylinder where gamma > 2:", " ".join(f"{v:.2f}" for v in cp.ravel()))

"""A sweep on one mesh, written run by run, then read by condition.

Potential flow past a cylinder at nine values of circulation, on one ring
of quadrilaterals. examples/matlab, julia and c hold the same program in
those languages, and all four print the same line.
"""
import numpy as np

import gamut
from _cylinder import pressure, ring

points, cells, t, r = ring()


def solve(gamma):
    """Stands for the solver: cp at every node for one value of circulation."""
    return pressure(t, r, gamma=gamma)


with gamut.create("cylinder.gamut", writer="example sweep", mesh="shared", per="fixed",
                   coordinates={"units": "m", "axes": 2},
                   parameters={"gamma": {"units": "m2 s-1", "role": "design"}},
                   fields={"cp": {"units": "1", "at": "node"}}) as study:
    study.set_mesh(points, cells)
    for gamma in np.linspace(0.0, 4.0, 9):
        study.add_run({"gamma": gamma}, fields={"cp": solve(gamma)})

with gamut.open("cylinder.gamut") as study:
    rows = study.select("gamma > 2")
    cp = study.get_field("cp", rows=rows, nodes=[12])     # runs x nodes
    print("cp on top of the cylinder where gamma > 2:", " ".join(f"{v:.2f}" for v in cp.ravel()))

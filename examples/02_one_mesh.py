"""Fields on one mesh shared by every run: eight runs written, a ninth
added, then read.

Flow past a cylinder with circulation (potential flow): every run uses the
same mesh, so node k is the same point in every run, and a field reads as
one block of runs x nodes. A region, or one node across every run, reads
without touching the rest. The MATLAB, Julia and C++ examples of this name
are the same program and print the same lines.
"""
import numpy as np

import gamut

# A ring of quadrilaterals around a unit cylinder: 48 points round, 12 out.
n_theta, n_r = 48, 12
theta = np.linspace(0, 2 * np.pi, n_theta, endpoint=False)
radius = np.geomspace(1.0, 6.0, n_r)
t, r = (a.ravel() for a in np.meshgrid(theta, radius))     # around each ring first
points = np.column_stack([r * np.cos(t), r * np.sin(t)])
quads = [[j * n_theta + i, j * n_theta + (i + 1) % n_theta,
          (j + 1) * n_theta + (i + 1) % n_theta, (j + 1) * n_theta + i]
         for j in range(n_r - 1) for i in range(n_theta)]
cells = (np.full(len(quads), 9, np.uint8),                  # VTK quadrilateral
         np.arange(0, 4 * len(quads) + 1, 4),
         np.array(quads).ravel())
surface = (np.arange(len(t)) < n_theta).astype(int)        # 1 ("wall") on the first ring


def solve(gamma):
    """Stands for the solver: cp at every node for one value of circulation."""
    u_theta = -np.sin(t) * (1 + 1 / r**2) + gamma / (2 * np.pi * r)
    u_r = np.cos(t) * (1 - 1 / r**2)
    return 1 - (u_r**2 + u_theta**2)                         # free stream speed 1


with gamut.create("cylinder.gamut", writer="example sweep", mesh="shared", per="fixed",
                   coordinates={"units": "m", "axes": 2},
                   parameters={"gamma": {"units": "m2 s-1", "role": "design"}},
                   mesh_labels={"surface": {"at": "node", "categories": ["field", "wall"]}},
                   fields={"cp": {"units": "1", "at": "node"}}) as study:
    study.set_mesh(points, cells, labels={"surface": surface})
    for gamma in np.linspace(0.0, 3.5, 8):
        study.add_run({"gamma": gamma}, fields={"cp": solve(gamma)})

with gamut.open("cylinder.gamut", mode="a") as study:
    study.add_run({"gamma": 4.0}, fields={"cp": solve(4.0)})

with gamut.open("cylinder.gamut") as study:
    print(study.type, "mesh,", study.row_count, "runs,", len(study.get_points()), "nodes")
    wall = study.categories("surface").index("wall")        # the code that means "wall"
    on_wall = np.flatnonzero(study.get_mesh_label("surface") == wall)
    lowest = study.get_field("cp", nodes=on_wall).min(axis=1)   # runs x wall nodes, per run
    print("lowest cp on the wall, by run:", " ".join(f"{v:.2f}" for v in lowest))
    top = study.get_field("cp", nodes=[12])                   # node 12, the top, in every run
    print("cp at the top of the cylinder, run by run:", " ".join(f"{v:.2f}" for v in top.ravel()))

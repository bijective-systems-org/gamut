"""Fields on one mesh shared by every run.

Flow past a cylinder with circulation (potential flow): every run uses the
same mesh, so node k is the same point in every run, and a field reads as
one block of runs x nodes. A region, or one node across every run, reads
without touching the rest.
"""
import numpy as np

import gamut

# A ring of quadrilaterals around a unit cylinder: 48 points round, 12 out.
n_theta, n_r = 48, 12
theta = np.linspace(0, 2 * np.pi, n_theta, endpoint=False)
radius = np.geomspace(1.0, 6.0, n_r)
t, r = np.meshgrid(theta, radius)
points = np.column_stack([(r * np.cos(t)).ravel(), (r * np.sin(t)).ravel()])
quads = [[j * n_theta + i, j * n_theta + (i + 1) % n_theta,
          (j + 1) * n_theta + (i + 1) % n_theta, (j + 1) * n_theta + i]
         for j in range(n_r - 1) for i in range(n_theta)]
cells = (np.full(len(quads), 9, np.uint8),                # VTK quadrilateral
         np.arange(0, 4 * len(quads) + 1, 4),
         np.array(quads).ravel())
surface = np.r_[np.ones(n_theta, int), np.zeros(n_theta * (n_r - 1), int)]   # wall: the first ring

with gamut.create("cylinder.gamut", writer="example sweep", mesh="shared", per="fixed",
                   coordinates={"units": "m", "axes": 2},
                   parameters={"gamma": {"units": "m2 s-1", "role": "design"}},
                   mesh_labels={"surface": {"at": "node", "categories": ["field", "wall"]}},
                   fields={"cp": {"units": "1", "at": "node"}}) as study:
    study.set_mesh(points, cells, labels={"surface": surface})
    for gamma in np.linspace(0.0, 4.0, 9):
        u_theta = -np.sin(t) * (1 + 1 / r**2) + gamma / (2 * np.pi * r)
        u_r = np.cos(t) * (1 - 1 / r**2)
        cp = 1 - (u_r**2 + u_theta**2)                     # free stream speed 1
        study.add_run({"gamma": gamma}, fields={"cp": cp.ravel()})

with gamut.open("cylinder.gamut") as study:
    print(study.type, "mesh,", study.row_count, "runs,", len(study.get_points()), "nodes")
    cp = study.get_field("cp")                             # runs x nodes
    print("cp block:", cp.shape)
    wall = study.categories("surface").index("wall")      # the code that means "wall"
    on_wall = np.flatnonzero(study.get_mesh_label("surface") == wall)
    print("lowest cp on the wall, by run:", study.get_field("cp", nodes=on_wall).min(axis=1).round(2))
    print("one node across every run:", study.get_field("cp", nodes=[12]).ravel().round(2))

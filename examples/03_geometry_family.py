"""A family of geometries that share one mesh topology.

Three cylinders of different radius, meshed with the same topology, so node
k is the same place on every member (a correspondence, which a mapping or
morphing tool builds for real geometry). Each member is run at several circulations. The
coordinates are stored once per member; fields stay one block of runs x
nodes, comparable node by node across the whole family.
"""
import numpy as np

import mestra
from _cylinder import pressure, ring

_, cells, _, _ = ring()
members = {"slim": 0.8, "base": 1.0, "wide": 1.2}

with mestra.create("family.mes", writer="example family", mesh="shared", per="group:member",
                   coordinates={"units": "m", "axes": 2},
                   labels={"member": {"role": "group", "categories": list(members)}},
                   generalisation_group="member",
                   parameters={"gamma": {"units": "m2 s-1", "role": "condition"}},
                   fields={"cp": {"units": "1", "at": "node"}}) as study:
    study.set_mesh(cells=cells, n_nodes=len(ring()[0]))
    for name, radius in members.items():
        points, _, t, r = ring(radius=radius)
        for gamma in (0.0, 2.0, 4.0):
            study.add_run({"member": name, "gamma": gamma},
                          fields={"cp": pressure(t, r, radius, gamma)}, points=points)

with mestra.open("family.mes") as study:
    print(study.row_count, "runs on", len(members), "members of one topology")
    for row in (0, 3, 6):
        member = study.get_label("member", rows=row)
        print(f"  row {row}: {member}, node 0 at x = {study.get_points(row=row)[0, 0]:.2f} m")
    print("cp at node 0 in every run:", study.get_field("cp", nodes=[0]).ravel().round(2))

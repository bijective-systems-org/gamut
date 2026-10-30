"""A family of geometries that share one mesh topology.

Three cylinders of different radius, meshed with the same topology, so node
k is the same place on every member (a correspondence, which a mapping or
morphing tool builds for real geometry). Each member is run at several circulations. The
coordinates are stored once per member; fields stay one block of runs x
nodes, comparable node by node across the whole family. The MATLAB, Julia
and C++ examples family are the same program and print the same lines.
"""
import gamut
from _cylinder import pressure, ring

_, cells, _, _ = ring()
members = {"slim": 0.8, "base": 1.0, "wide": 1.2}

with gamut.create("family.gamut", writer="example family", mesh="shared", per="group:member",
                   coordinates={"units": "m", "axes": 2},
                   labels={"member": {"role": "group", "categories": list(members)},
                           "split": {"role": "split", "categories": ["train", "test"]}},
                   generalisation_group="member",
                   parameters={"gamma": {"units": "m2 s-1", "role": "condition"}},
                   fields={"cp": {"units": "1", "at": "node"}}) as study:
    study.set_mesh(cells=cells, n_nodes=len(ring()[0]))
    for name, radius in members.items():
        points, _, t, r = ring(radius=radius)
        for gamma in (0.0, 2.0, 4.0):
            study.add_run({"member": name, "gamma": gamma,
                           "split": "test" if name == "wide" else "train"},
                          fields={"cp": pressure(t, r, radius, gamma)}, points=points)

with gamut.open("family.gamut") as study:
    print(study.row_count, "runs on", len(members), "members of one topology")
    for name in members:
        first = study.select(f"member == {name}")[0]
        print(f"  {name}: first node at x = {study.get_points(row=first)[0, 0]:.2f} m")
    cp = study.get_field("cp", nodes=[0]).ravel()
    print("cp at the first node, run by run:", " ".join(f"{v:.2f}" for v in cp))
    test = study.select("split == test")
    print("held out for testing:", len(test), "runs of", ", ".join(sorted(set(study.get_label("member", rows=test)))))

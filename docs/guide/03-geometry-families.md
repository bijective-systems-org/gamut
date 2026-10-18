# 3. Geometry families

A design study often runs several shapes, each at several conditions. When
the shapes are meshed with one topology, node k is the same place on every
shape (a correspondence, which a mapping or morphing tool builds for real
geometry), so fields compare node by node across the whole family. The
file keeps one mesh, stores each member's coordinates once, and keeps
every field as one block of runs × nodes.

The example is three cylinders of different radius, each run at three
circulations.

## Writing

```python
with gamut.create("family.gamut", writer="example family", mesh="shared", per="group:member",
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
```

- `per="group:member"`: the geometry changes from one member of the
  `member` label to the next, and is the same for every run of a member.
  The label's role is `group`: rows that belong together.
- `set_mesh` gives the cells and the node count once; the coordinates come
  with the runs.
- Each run of a member may pass its points; the first sets the member's
  geometry, and a later one must be the same (a different geometry for
  the same member is refused).
- `generalisation_group="member"` records that a fair test of a model
  trained on this study holds out whole members. A published split that
  puts runs of one member on both sides is reported.

## Reading

```python
with gamut.open("family.gamut") as study:
    print(study.row_count, "runs on", len(members), "members of one topology")
    for row in (0, 3, 6):
        member = study.get_label("member", rows=row)
        print(f"  row {row}: {member}, node 0 at x = {study.get_points(row=row)[0, 0]:.2f} m")
    print("cp at node 0 in every run:", study.get_field("cp", nodes=[0]).ravel().round(2))
```

```text
9 runs on 3 members of one topology
  row 0: slim, node 0 at x = 0.80 m
  row 3: base, node 0 at x = 1.00 m
  row 6: wide, node 0 at x = 1.20 m
cp at node 0 in every run: [1.   0.84 0.37 1.   0.9  0.59 1.   0.93 0.72]
```

`get_points(row=...)` returns the geometry a run used, whatever `per` is.
Node 0 sits on each cylinder's wall where the flow stops when there is no
circulation, so its pressure coefficient is 1 there on every member, and
falls by less on the larger cylinders as circulation grows.

## Worth knowing

- `per="run"` is the same idea with a geometry per run: a mesh that
  deforms with every run, such as an aeroelastic or optimisation history.
- Coordinates are always absolute positions, never displacements.
- When the members are meshed separately, with different node counts or
  connectivity, the study is a [changing mesh](04-changing-meshes.md)
  instead, and fields no longer compare node by node.

Run it: `python examples/03_geometry_family.py`. Next: [changing meshes](04-changing-meshes.md).

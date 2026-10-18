# 4. Changing meshes

Some studies cannot share a mesh: a refinement study, an adaptive solver,
a family whose members were meshed separately. The file then keeps a mesh
for each run (or for each member of a group), and fields as each run's
values on its own mesh.

The example runs the same flow on three meshes of increasing resolution,
with the pressure stored per cell as a finite-volume solver reports it.

## Writing

```python
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
```

- `mesh="changing"` with `per="run"`: every run brings its own points and
  cells. `per="group:<label>"` gives one mesh per member of a group label
  instead, shared by that member's runs.
- A field's values for a run match that run's node or cell count.

## Reading

```python
with gamut.open("refinement.gamut") as study:
    for row in range(study.row_count):
        types, offsets, connectivity = study.get_cells(row=row)
        cp = study.get_field("cp", rows=row)
        print(f"row {row}: {len(study.get_points(row=row))} nodes, {len(types)} cells, "
              f"lowest cell cp {cp.min():.3f}")
```

```text
row 0: 144 nodes, 120 cells, lowest cell cp -1.804
row 1: 576 nodes, 528 cells, lowest cell cp -2.399
row 2: 2304 nodes, 2208 cells, lowest cell cp -2.700
```

Reads take one run at a time. The lowest cell value approaches the exact
−3 as the cells next to the wall shrink.

## Worth knowing

- Nothing in a changing-mesh file claims that node k of one run relates to
  node k of another, so reads across runs (one node in every run, a block
  of runs × nodes) are refused with a message that says so.
- To compare such runs node by node, map them onto one topology first,
  then write them as a [family](03-geometry-families.md).
- The meshes and fields are stored end to end with offsets, the
  arrangement VTKHDF uses for meshes that change from step to step.

Run it: `python examples/04_changing_mesh.py`. Next: [time series](05-time-series.md).

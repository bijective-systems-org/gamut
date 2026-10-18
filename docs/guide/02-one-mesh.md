# 2. One mesh

When every run uses the same mesh, node k is the same point in every run.
The file stores the mesh once, and each field as one block of runs ×
nodes, so one run, one region of every run, or one node across every run
is a single read. The example is potential flow past a cylinder at nine
values of circulation.

## Writing

```python
with mestra.create("cylinder.mes", writer="example sweep", mesh="shared", per="fixed",
                   coordinates={"units": "m", "axes": 2},
                   parameters={"gamma": {"units": "m2 s-1", "role": "design"}},
                   mesh_labels={"surface": {"at": "node", "categories": ["field", "wall"]}},
                   fields={"cp": {"units": "1", "at": "node"}}) as study:
    study.set_mesh(points, cells, labels={"surface": surface})
```

- `mesh="shared", per="fixed"`: one mesh, and one geometry, for every run.
  ([Families](03-geometry-families.md) keep the mesh and change the
  geometry; [changing meshes](04-changing-meshes.md) change both.)
- **Coordinates** have units and one to three axes.
- **Cells** are three arrays in VTK's convention: a cell type per cell
  (9 is a quadrilateral, 5 a triangle, 12 a hexahedron), offsets where each
  cell's nodes start in the third array (one more entry than there are
  cells, starting at 0), and the node numbers, counted from 0. A mesh
  without cells is a point cloud: pressure taps, probes.
- **Mesh labels** describe the mesh: zones, boundary patches, materials.
  This one marks the nodes on the cylinder's wall.
- **Fields** live at nodes or at cells; `at` says which, and the length of
  every run's values is checked against it.

Each run then brings its parameters and its fields:

```python
study.add_run({"gamma": gamma}, fields={"cp": cp.ravel()})
```

## Reading

```python
with mestra.open("cylinder.mes") as study:
    print(study.type, "mesh,", study.row_count, "runs,", len(study.get_points()), "nodes")
    cp = study.get_field("cp")                             # runs x nodes
    print("cp block:", cp.shape)
    wall = study.categories("surface").index("wall")      # the code that means "wall"
    on_wall = np.flatnonzero(study.get_mesh_label("surface") == wall)
    print("lowest cp on the wall, by run:", study.get_field("cp", nodes=on_wall).min(axis=1).round(2))
    print("one node across every run:", study.get_field("cp", nodes=[12]).ravel().round(2))
```

```text
shared mesh, 9 runs, 576 nodes
cp block: (9, 576)
lowest cp on the wall, by run: [-3.   -3.32 -3.66 -4.01 -4.37 -4.75 -5.14 -5.54 -5.95]
one node across every run: [-3.   -2.69 -2.39 -2.1  -1.83 -1.57 -1.32 -1.08 -0.86]
```

`get_field` takes `rows` and `nodes` (or `cells`): a position, a list of
positions, a slice, or nothing for all. A read decompresses only the
stored chunks that hold what it asks for. A mesh label is stored as a code
per node, and `categories` says which name each code stands for.

## Worth knowing

- The first run without circulation gives the textbook minimum of −3 at
  the top and bottom of the cylinder; circulation deepens one side.
- Fields are compressed in chunks of about 256 KB. On a small mesh a
  chunk holds many whole runs; on a mesh of more than about 32,000 nodes it
  holds part of one run, so a region of every run reads a small part of
  the file ([benchmarks](../benchmarks.md)).
- A `per = fixed` mesh's points and cells are written once however many
  runs the file holds.

Run it: `python examples/02_one_mesh.py`. Next: [geometry families](03-geometry-families.md).

# 2. One mesh

When every run uses the same mesh, node k is the same point in every run.
The file stores the mesh once, and each field as one block of runs ×
nodes, so one run, one region of every run, or one node across every run
is a single read. The example is potential flow past a cylinder: eight
values of circulation written, a ninth added by reopening the file. It is
the same program in each language.

## Writing

/// tab | Python

```python
with gamut.create("cylinder.gamut", writer="example sweep", mesh="shared", per="fixed",
                   coordinates={"units": "m", "axes": 2},
                   parameters={"gamma": {"units": "m2 s-1", "role": "design"}},
                   mesh_labels={"surface": {"at": "node", "categories": ["field", "wall"]}},
                   fields={"cp": {"units": "1", "at": "node"}}) as study:
    study.set_mesh(points, cells, labels={"surface": surface})
    for gamma in np.linspace(0.0, 3.5, 8):
        study.add_run({"gamma": gamma}, fields={"cp": solve(gamma)})
```

///

/// tab | MATLAB

```matlab
study = gamut.create('cylinder.gamut', 'writer', 'example sweep', 'mesh', 'shared', 'per', 'fixed', ...
    'coordinates', struct('units', 'm', 'axes', 2), ...
    'parameters', struct('gamma', struct('units', 'm2 s-1', 'role', 'design')), ...
    'meshLabels', struct('surface', struct('at', 'node', 'categories', {{'field', 'wall'}})), ...
    'fields', struct('cp', struct('units', '1', 'at', 'node')));
study.setMesh(points, cells, struct('surface', surface));
for gamma = linspace(0, 3.5, 8)
    study.addRun(struct('gamma', gamma), 'fields', struct('cp', solve(gamma)));
end
study.close();
```

///

/// tab | Julia

```julia
Gamut.create("cylinder.gamut"; writer="example sweep", mesh="shared", per="fixed",
              coordinates=(units="m", axes=2),
              parameters=Dict("gamma" => (units="m2 s-1", role="design")),
              mesh_labels=Dict("surface" => (at="node", categories=["field", "wall"])),
              fields=Dict("cp" => (units="1", at="node"))) do study
    Gamut.set_mesh!(study; points, cells, labels=Dict("surface" => surface))
    for gamma in range(0, 3.5; length=8)
        Gamut.add_run!(study, Dict("gamma" => gamma); fields=Dict("cp" => solve(gamma)))
    end
end
```

///

/// tab | C++

```cpp
auto study = gamut::create("cylinder.gamut", "example sweep", "shared", "fixed");
study.declare_coordinates("m", 2);
study.declare_parameter("gamma", "design", "m2 s-1");
study.declare_mesh_label("surface", "node", {"field", "wall"});
study.declare_field("cp", "node", "1");
study.set_mesh(points, cells, {{"surface", surface}});
for (double gamma = 0.0; gamma < 3.75; gamma += 0.5)
  study.add_run({{"gamma", gamma}}, {{"cp", solve(gamma)}});
study.close();
```

///

/// tab | Rust

```rust
let mut study = gamut::create("cylinder.gamut", "example sweep", "shared", "fixed")?;
study.declare_coordinates("m", 2)?;
study.declare_parameter("gamma", "design", "m2 s-1")?;
study.declare_mesh_label("surface", "node", &["field", "wall"])?;
study.declare_field("cp", "node", "1")?;
study.set_mesh(&points, &cells, &[("surface", &surface)])?;
for gamma in (0..8).map(|i| 0.5 * i as f64) {
    study.add_run(&[("gamma", gamma.into())], &[("cp", &solve(&t, &r, gamma))])?;
}
study.close()?;
```

///

`points`, `cells` and `surface` (a code per node: 1 on the wall, 0
elsewhere) are built at the top of each example program, and `solve`
stands for the solver, returning `cp` at every node.

- A shared mesh, fixed for every run: one mesh, and one geometry.
  ([Families](03-geometry-families.md) keep the mesh and change the
  geometry; [changing meshes](04-changing-meshes.md) change both.)
- Coordinates have units and one to three axes.
- Cells are three arrays in VTK's convention: a cell type per cell
  (9 is a quadrilateral, 5 a triangle, 12 a hexahedron, 3 a line segment
  for a contour such as an airfoil's surface), offsets where each
  cell's nodes start in the third array (one more entry than there are
  cells, starting at 0), and the node numbers, counted from 0 in every
  language. A mesh without cells is a point cloud: pressure taps, probes.
- Mesh labels describe the mesh: zones, boundary patches, materials.
  This one marks the nodes on the cylinder's wall.
- Fields live at nodes or at cells; `at` says which, and the length of
  every run's values is checked against it.
- Each run gives its parameters and its fields: here `gamma`, and `cp`
  at every node.

## Adding runs

Reopening the file adds a ninth run:

/// tab | Python

```python
with gamut.open("cylinder.gamut", mode="a") as study:
    study.add_run({"gamma": 4.0}, fields={"cp": solve(4.0)})
```

///

/// tab | MATLAB

```matlab
study = gamut.open('cylinder.gamut', 'mode', 'a');
study.addRun(struct('gamma', 4), 'fields', struct('cp', solve(4)));
study.close();
```

///

/// tab | Julia

```julia
Gamut.open("cylinder.gamut"; mode="a") do study
    Gamut.add_run!(study, Dict("gamma" => 4.0); fields=Dict("cp" => solve(4.0)))
end
```

///

/// tab | C++

```cpp
study = gamut::open("cylinder.gamut", "a");
study.add_run({{"gamma", 4.0}}, {{"cp", solve(4.0)}});
study.close();
```

///

/// tab | Rust

```rust
let mut study = gamut::open_append("cylinder.gamut")?;
study.add_run(&[("gamma", 4.0.into())], &[("cp", &solve(&t, &r, 4.0))])?;
study.close()?;
```

///

## Reading

/// tab | Python

```python
with gamut.open("cylinder.gamut") as study:
    print(study.type, "mesh,", study.row_count, "runs,", len(study.get_points()), "nodes")
    wall = study.categories("surface").index("wall")           # the code that means "wall"
    on_wall = np.flatnonzero(study.get_mesh_label("surface") == wall)
    lowest = study.get_field("cp", nodes=on_wall).min(axis=1)  # runs x wall nodes; each run's lowest
    print("lowest cp on the wall, by run:", " ".join(f"{v:.2f}" for v in lowest))
    top = study.get_field("cp", nodes=[12])                    # node 12, the top, in every run
    print("cp at the top of the cylinder, run by run:", " ".join(f"{v:.2f}" for v in top.ravel()))
```

///

/// tab | MATLAB

```matlab
study = gamut.open('cylinder.gamut');
fprintf('%s mesh, %d runs, %d nodes\n', study.type(), study.rowCount(), size(study.getPoints(), 1));
wall = find(strcmp(study.categories('surface'), 'wall')) - 1;  % the code that means 'wall'
onWall = find(study.getMeshLabel('surface') == wall);
lowest = min(study.getField('cp', 'nodes', onWall), [], 2);    % runs x wall nodes; each run's lowest
fprintf('lowest cp on the wall, by run:%s\n', sprintf(' %.2f', lowest));
top = study.getField('cp', 'nodes', 13);                       % node 13, the top, in every run
study.close();
fprintf('cp at the top of the cylinder, run by run:%s\n', sprintf(' %.2f', top));
```

///

/// tab | Julia

```julia
Gamut.open("cylinder.gamut") do study
    println(study.type, " mesh, ", study.row_count, " runs, ", size(Gamut.get_points(study), 1), " nodes")
    wall = findfirst(==("wall"), Gamut.categories(study, "surface")) - 1   # the code that means "wall"
    on_wall = findall(==(wall), vec(Gamut.get_mesh_label(study, "surface")))
    lowest = minimum(Gamut.get_field(study, "cp"; nodes=on_wall); dims=2)  # runs × wall nodes; each run's lowest
    println("lowest cp on the wall, by run: ", join((@sprintf("%.2f", v) for v in lowest), " "))
    top = Gamut.get_field(study, "cp"; nodes=[13])                         # node 13, the top, in every run
    println("cp at the top of the cylinder, run by run: ", join((@sprintf("%.2f", v) for v in top), " "))
end
```

///

/// tab | C++

```cpp
study = gamut::open("cylinder.gamut");
std::printf("%s mesh, %lld runs, %lld nodes\n", study.type().c_str(), (long long)study.row_count(),
            (long long)study.get_points().shape[0]);
const auto names = study.categories("surface");
// The code that means "wall" is its place in the table.
const int64_t wall = std::find(names.begin(), names.end(), "wall") - names.begin();
std::vector<int64_t> on_wall;
const auto label = study.get_mesh_label("surface");
for (int64_t k = 0; k < int64_t(label.size()); ++k)
  if (label[size_t(k)] == wall) on_wall.push_back(k);
const auto block = study.get_field("cp", gamut::all, on_wall);  // runs x wall nodes
std::printf("lowest cp on the wall, by run:");
for (int64_t run = 0; run < block.shape[0]; ++run) {
  double lowest = block(run, 0);
  for (int64_t k = 1; k < block.shape[1]; ++k) lowest = std::min(lowest, block(run, k));
  std::printf(" %.2f", lowest);
}
std::printf("\n");
const auto top = study.get_field("cp", gamut::all, {12});       // node 12, the top, in every run
std::printf("cp at the top of the cylinder, run by run:");
for (double v : top) std::printf(" %.2f", v);
std::printf("\n");
```

///

/// tab | Rust

```rust
let study = gamut::open("cylinder.gamut")?;
println!("{} mesh, {} runs, {} nodes", study.type_()?, study.row_count()?, study.get_points(None)?.shape[0]);
let names = study.categories("surface")?;
// The code that means "wall" is its place in the table.
let wall = names.iter().position(|n| n == "wall").unwrap() as i64;
let label = study.get_mesh_label("surface", None)?;
let on_wall: Vec<usize> = (0..label.len()).filter(|&k| label[k] == wall).collect();
let block = study.get_field("cp", .., on_wall)?;   // runs x wall nodes
let lowest = (0..block.shape[0])
    .map(|run| (0..block.shape[1]).map(|k| block[[run, k]]).fold(f64::INFINITY, f64::min));
println!("lowest cp on the wall, by run:{}", lowest.map(|v| format!(" {v:.2}")).collect::<String>());
let top = study.get_field("cp", .., 12)?;   // node 12, the top, in every run
println!("cp at the top of the cylinder, run by run:{}",
         top.values.iter().map(|v| format!(" {v:.2}")).collect::<String>());
```

///

Each prints:

```text
shared mesh, 9 runs, 576 nodes
lowest cp on the wall, by run: -3.00 -3.32 -3.66 -4.01 -4.37 -4.75 -5.14 -5.54 -5.95
cp at the top of the cylinder, run by run: -3.00 -2.69 -2.39 -2.10 -1.83 -1.57 -1.32 -1.08 -0.86
```

`get_field` (`getField` in MATLAB) takes the rows and the nodes (or cells)
to read, all of them when left out; in C++ and Rust the rows come first,
and `gamut::all` (`..` in Rust) reads every run. MATLAB and Julia count
positions from 1, so the top of the cylinder is node 13 there and node 12
in Python, C++ and Rust. A
mesh label is stored as a code per node, counted from 0 in every language,
and `categories` says which name each code stands for: in MATLAB and
Julia the wall's code is its place in `categories` minus one. A read
decompresses only the stored chunks that hold what it asks for.

## Notes

- The first run without circulation gives the textbook minimum of −3 at
  the top and bottom of the cylinder; circulation deepens one side.
- Fields are compressed in chunks of about 256 KB. On a small mesh a
  chunk holds many whole runs; on a mesh of more than about 32,000 nodes it
  holds part of one run, so a region of every run reads a small part of
  the file ([benchmarks](../benchmarks.md)).
- A `per = fixed` mesh's points and cells are written once however many
  runs the file holds.

Run it: `python examples/02_one_mesh.py`, or `one_mesh` from
`examples/matlab`, `examples/julia` and `examples/cpp`
([installing](../install.md) says how to run each). Next:
[geometry families](03-geometry-families.md).

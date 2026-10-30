# 4. Changing meshes

Some studies cannot share a mesh: a refinement study, an adaptive solver,
a family whose members were meshed separately. The file then keeps a mesh
for each run (or for each member of a group), and fields as each run's
values on its own mesh.

The example runs the same flow on three meshes of increasing resolution,
with the pressure stored per cell as a finite-volume solver reports it,
at each cell's centre. `ring` and `pressure` are the mesher and solver of
the [geometry families](03-geometry-families.md) example.

## Writing

/// tab | Python

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

///

/// tab | MATLAB

```matlab
study = gamut.create('refinement.gamut', 'writer', 'example refinement', 'mesh', 'changing', 'per', 'run', ...
    'coordinates', struct('units', 'm', 'axes', 2), ...
    'parameters', struct('cells_round', struct('units', '1', 'role', 'design')), ...
    'scalars', struct('cp_min', '1'), ...
    'fields', struct('cp', struct('units', '1', 'at', 'cell')));
for n = [24 48 96]
    [points, cells] = cylinderRing(1, n, n / 4);
    corners = reshape(cells{3}, 4, []) + 1;                         % four nodes per quad, from 1
    x = mean(reshape(points(corners, 1), 4, []))';
    y = mean(reshape(points(corners, 2), 4, []))';
    cp = cylinderPressure(atan2(y, x), hypot(x, y), 1, 0);
    study.addRun(struct('cells_round', n, 'cp_min', min(cp)), 'fields', struct('cp', cp), ...
        'points', points, 'cells', cells);
end
study.close();
```

///

/// tab | Julia

```julia
Gamut.create("refinement.gamut"; writer="example refinement", mesh="changing", per="run",
              coordinates=(units="m", axes=2),
              parameters=Dict("cells_round" => (units="1", role="design")),
              scalars=Dict("cp_min" => "1"),
              fields=Dict("cp" => (units="1", at="cell"))) do study
    for n in (24, 48, 96)
        points, cells, _, _ = ring(; n_theta=n, n_r=n ÷ 4)
        corners = reshape(cells[3], 4, :) .+ 1                      # four nodes per quad, from 1
        x = vec(sum(points[corners, 1]; dims=1)) ./ 4
        y = vec(sum(points[corners, 2]; dims=1)) ./ 4
        cp = pressure(atan.(y, x), hypot.(x, y))
        Gamut.add_run!(study, Dict("cells_round" => n, "cp_min" => minimum(cp));
                       fields=Dict("cp" => cp), points, cells)
    end
end
```

///

/// tab | C++

```cpp
auto study = gamut::create("refinement.gamut", "example refinement", "changing", "run");
study.declare_coordinates("m", 2);
study.declare_parameter("cells_round", "design", "1");
study.declare_scalar("cp_min", "1");
study.declare_field("cp", "cell", "1");
for (const int n : {24, 48, 96}) {
  const Ring g = ring(n, n / 4);
  std::vector<double> t, r;                       // each cell's centre, in polar coordinates
  for (size_t c = 0; c + 1 < g.cells.offsets.size(); ++c) {
    double x = 0, y = 0;
    for (int64_t k = g.cells.offsets[c]; k < g.cells.offsets[c + 1]; ++k) {
      x += g.points[2 * g.cells.connectivity[k]];
      y += g.points[2 * g.cells.connectivity[k] + 1];
    }
    t.push_back(std::atan2(y / 4, x / 4));
    r.push_back(std::hypot(x / 4, y / 4));
  }
  const std::vector<double> cp = pressure(t, r);
  study.add_run({{"cells_round", double(n)}, {"cp_min", *std::min_element(cp.begin(), cp.end())}},
                {{"cp", cp}}, gamut::Geometry{g.points, g.cells, {}});
}
study.close();
```

///

- The mesh is `changing` and `per` `run`: every run brings its own points
  and cells. `per` `group:<label>` gives one mesh per member of a group
  label instead, shared by that member's runs.
- A field's values for a run match that run's node or cell count.

## Reading

/// tab | Python

```python
with gamut.open("refinement.gamut") as study:
    rounds = study.get_parameter("cells_round")
    for row in range(study.row_count):
        types, offsets, connectivity = study.get_cells(row=row)
        cp = study.get_field("cp", rows=row)
        print(f"{rounds[row]:g} cells round: {len(study.get_points(row=row))} nodes, {len(types)} cells, "
              f"lowest cell cp {cp.min():.3f}")
```

///

/// tab | MATLAB

```matlab
study = gamut.open('refinement.gamut');
rounds = study.getParameter('cells_round');
for row = 1:study.rowCount()
    types = study.getCells(row);
    cp = study.getField('cp', 'rows', row);
    fprintf('%g cells round: %d nodes, %d cells, lowest cell cp %.3f\n', rounds(row), ...
        size(study.getPoints(row), 1), numel(types), min(cp));
end
study.close();
```

///

/// tab | Julia

```julia
Gamut.open("refinement.gamut") do study
    rounds = Gamut.get_parameter(study, "cells_round")
    for row in 1:study.row_count
        types, _, _ = Gamut.get_cells(study; row)
        cp = Gamut.get_field(study, "cp"; rows=row)
        @printf("%g cells round: %d nodes, %d cells, lowest cell cp %.3f\n", rounds[row],
                size(Gamut.get_points(study; row), 1), length(types), minimum(cp))
    end
end
```

///

/// tab | C++

```cpp
study = gamut::open("refinement.gamut");
const std::vector<double> rounds = study.get_parameter<double>("cells_round");
for (int64_t row = 0; row < study.row_count(); ++row) {
  const gamut::Cells cells = study.get_cells(row);
  const std::vector<double> cp = study.get_field("cp", {row}).values;
  std::printf("%g cells round: %lld nodes, %zu cells, lowest cell cp %.3f\n", rounds[size_t(row)],
              (long long)study.get_points(row).shape[0], cells.types.size(),
              *std::min_element(cp.begin(), cp.end()));
}
```

///

Each prints:

```text
24 cells round: 144 nodes, 120 cells, lowest cell cp -1.804
48 cells round: 576 nodes, 528 cells, lowest cell cp -2.399
96 cells round: 2304 nodes, 2208 cells, lowest cell cp -2.700
```

Reads take one run at a time. The lowest cell value approaches the exact
−3 as the cells next to the wall shrink.

## Notes

- Nothing in a changing-mesh file claims that node k of one run relates to
  node k of another, so reads across runs (one node in every run, a block
  of runs × nodes) are refused with a message that says so.
- To compare such runs node by node, map them onto one topology first,
  then write them as a [family](03-geometry-families.md).
- The meshes and fields are stored end to end with offsets, the
  arrangement VTKHDF uses for meshes that change from step to step.

Run it: `python examples/04_changing_mesh.py`, or `refinement` from
`examples/matlab`, `examples/julia` and `examples/cpp`
([installing](../install.md) says how to run each). Next:
[time series](05-time-series.md).

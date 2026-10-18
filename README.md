<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/bijective-systems-org/gamut/main/docs/assets/logo-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/bijective-systems-org/gamut/main/docs/assets/logo.svg">
    <img src="https://raw.githubusercontent.com/bijective-systems-org/gamut/main/docs/assets/logo-any.svg" alt="Gamut" width="240">
  </picture>
</p>

<p align="center">
An open file format for parametric simulation studies,<br>
with libraries for Python, MATLAB, Julia and C.
</p>

<p align="center">
  <a href="https://github.com/bijective-systems-org/gamut/actions/workflows/ci.yml"><img src="https://github.com/bijective-systems-org/gamut/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI"></a>
</p>

---

Gamut is a file format for parametric simulation studies: the hundreds or
thousands of CFD or FEA runs behind a design sweep, an aerodynamic
database or a surrogate model. One file holds every run's inputs, results,
status, mesh and fields, with units, and Python, MATLAB, Julia and C query
it with the same calls.

## Example

Nine runs of potential flow past a cylinder on one mesh: eight written as
a sweep, a ninth added later, then read back by condition. `points`,
`cells` and `solve` stand for your mesh and your solver; each file in
[`examples/`](https://github.com/bijective-systems-org/gamut/blob/main/examples) is the complete program.

### Read

The pressure at the top of the cylinder in every run with circulation
above 2:

Python

```python
with gamut.open("cylinder.gamut") as study:
    rows = study.select("gamma > 2")
    cp = study.get_field("cp", rows=rows, nodes=[12])     # runs x nodes
```

MATLAB

```matlab
study = gamut.open('cylinder.gamut');
rows = study.select('gamma > 2');
cp = study.getField('cp', 'rows', rows, 'nodes', 13);           % runs x nodes, from 1
study.close();
```

Julia

```julia
cp = Gamut.open("cylinder.gamut") do study
    rows = Gamut.select(study, "gamma > 2")
    Gamut.get_field(study, "cp"; rows, nodes=[13])           # runs × nodes, from 1
end
```

C

```c
CHECK(gamut_open("cylinder.gamut", &f, &err));
int64_t rows[9], n = 0, node = 12;
CHECK(gamut_select(f, "gamma > 2", rows, 9, &n, &err));
const gamut_sel chosen = {GAMUT_SEL_INDEX, 0, 0, rows, n};
const gamut_sel one_node = {GAMUT_SEL_INDEX, 0, 0, &node, 1};
double values[9];
CHECK(gamut_read(f, "cp", &chosen, &one_node, GAMUT_FLOAT64, values, sizeof values, &err));
```

All four print the same values:

```text
cp on top of the cylinder where gamma > 2: -1.57 -1.32 -1.08 -0.86
```

MATLAB and Julia count positions from 1, so node 12 in Python and C is
node 13 in MATLAB and Julia.

### Write

Declare each name with its units and role, give the mesh once, then add
runs as the solver finishes them:

Python

```python
with gamut.create("cylinder.gamut", writer="example sweep", mesh="shared", per="fixed",
                   coordinates={"units": "m", "axes": 2},
                   parameters={"gamma": {"units": "m2 s-1", "role": "design"}},
                   fields={"cp": {"units": "1", "at": "node"}}) as study:
    study.set_mesh(points, cells)
    for gamma in np.linspace(0.0, 3.5, 8):
        study.add_run({"gamma": gamma}, fields={"cp": solve(gamma)})
```

MATLAB

```matlab
study = gamut.create('cylinder.gamut', 'writer', 'example sweep', 'mesh', 'shared', 'per', 'fixed', ...
    'coordinates', struct('units', 'm', 'axes', 2), ...
    'parameters', struct('gamma', struct('units', 'm2 s-1', 'role', 'design')), ...
    'fields', struct('cp', struct('units', '1', 'at', 'node')));
study.setMesh(points, cells);
for gamma = linspace(0, 3.5, 8)
    study.addRun(struct('gamma', gamma), 'fields', struct('cp', solve(gamma)));
end
study.close();
```

Julia

```julia
Gamut.create("cylinder.gamut"; writer="example sweep", mesh="shared", per="fixed",
              coordinates=(units="m", axes=2),
              parameters=Dict("gamma" => (units="m2 s-1", role="design")),
              fields=Dict("cp" => (units="1", at="node"))) do study
    Gamut.set_mesh!(study; points, cells)
    for gamma in range(0, 3.5; length=8)
        Gamut.add_run!(study, Dict("gamma" => gamma); fields=Dict("cp" => solve(gamma)))
    end
end
```

C

```c
static void add_run(gamut_file* f, double gamma) {
  static double cp[N_NODES];
  solve(gamma, cp);
  CHECK(gamut_batch_begin(f, 1, &err));
  CHECK(gamut_batch_values(f, "gamma", GAMUT_FLOAT64, &gamma, 1, &err));
  CHECK(gamut_batch_values(f, "cp", GAMUT_FLOAT64, cp, N_NODES, &err));
  CHECK(gamut_batch_commit(f, NULL, &err));
}
```

```c
CHECK(gamut_create("cylinder.gamut", "example sweep", "shared", "fixed", &f, &err));
CHECK(gamut_declare_coordinates(f, "m", GAMUT_FLOAT64, 2, "", "", &err));
CHECK(gamut_declare_parameter(f, "gamma", "design", "m2 s-1", GAMUT_FLOAT64, 0, 0, 0, "", &err));
CHECK(gamut_declare_result(f, "cp", "node", "1", GAMUT_FLOAT64, "", "", 0, 0, "", "", "", "", -1,
                         "", "", &err));
CHECK(gamut_geometry_begin(f, &err));
CHECK(gamut_geometry_points(f, GAMUT_FLOAT64, points, N_NODES, 2, &err));
CHECK(gamut_geometry_cells(f, types, N_CELLS, offsets, connectivity, 4 * N_CELLS, &err));
CHECK(gamut_set_mesh(f, &err));
for (int run = 0; run < 8; ++run) add_run(f, 0.5 * run);
CHECK(gamut_close(f, &err));
```

### Add runs

Reopen the file and add to it, from any of the four:

Python

```python
with gamut.open("cylinder.gamut", mode="a") as study:
    study.add_run({"gamma": 4.0}, fields={"cp": solve(4.0)})
```

MATLAB

```matlab
study = gamut.open('cylinder.gamut', 'mode', 'a');
study.addRun(struct('gamma', 4), 'fields', struct('cp', solve(4)));
study.close();
```

Julia

```julia
Gamut.open("cylinder.gamut"; mode="a") do study
    Gamut.add_run!(study, Dict("gamma" => 4.0); fields=Dict("cp" => solve(4.0)))
end
```

C

```c
CHECK(gamut_open_append("cylinder.gamut", &f, &err));
add_run(f, 4.0);
CHECK(gamut_close(f, &err));
```

## What you can do with it

| | |
|---|---|
| Use one file everywhere | Python, MATLAB, Julia and C call one C++ core, so a query returns the same values in each, and each reads what another wrote. h5py, xarray and the netCDF tools open the files without Gamut. |
| Read only what you need | Choose runs by condition (`mach > 0.7 and status == converged`), nodes by zone, and values in the units you ask for. On a shared mesh, one region of every run or one node across thousands of runs is a single read ([reading parts](https://github.com/bijective-systems-org/gamut/blob/main/docs/guide/08-reading-parts.md)). |
| Train models on it directly | Each field on a shared mesh is one block of runs × nodes. Labels record status, fidelity or solver, a split says which rows are for training and which for testing, and a file can name the group a fair test must hold out whole. Standard deviations, quantiles and derivatives are stored beside the results they describe ([run tables](https://github.com/bijective-systems-org/gamut/blob/main/docs/guide/01-run-tables.md), [uncertainty](https://github.com/bijective-systems-org/gamut/blob/main/docs/guide/06-uncertainty-and-gradients.md)). |
| Keep the model with the data | A fitted model is a file of the same shape with no runs and no code inside; evaluating it on new inputs gives an ordinary study ([models](https://github.com/bijective-systems-org/gamut/blob/main/docs/guide/07-models.md)). |
| Store any study | A table of runs with no mesh, one mesh for every run, one geometry per member of a family of shapes on one topology, a mesh per run, or transient runs with a row per saved step ([families](https://github.com/bijective-systems-org/gamut/blob/main/docs/guide/03-geometry-families.md), [time series](https://github.com/bijective-systems-org/gamut/blob/main/docs/guide/05-time-series.md)). |
| Rely on what you open | Every number has units, refused when missing; Python converts them on read and write. `gamut validate` checks the 34 numbered rules of the [specification](https://github.com/bijective-systems-org/gamut/blob/main/SPEC.md). A corpus of 64 valid, broken and hostile files runs in CI through the Python, MATLAB and Julia libraries and the C interface under them, and readers check sizes before allocating memory and never follow links ([files from outside](https://github.com/bijective-systems-org/gamut/blob/main/docs/security.md)). |

## Performance

<p align="center">
  <img src="https://raw.githubusercontent.com/bijective-systems-org/gamut/main/docs/assets/bench-summary.svg" alt="Size on disk and three read times for one study stored as Gamut, HDF5 with a group per run, netCDF-4, Zarr and VTK files." width="760">
</p>

Gamut is about the size of netCDF-4 and Zarr, a sixth of the VTK files,
and in this study the fastest at choosing runs by condition. Its chunks are laid out for
reading whole runs, so one node across every run is slower than in
netCDF-4 or Zarr; four threads bring it from 124 ms to 38 ms. HDF5 itself
decompresses on one core, so Gamut fetches the compressed chunks through
HDF5 and decompresses them in its own threads. On a second study, with
177,000-node meshes, one run reads in 15 ms against 124 ms from its VTK
file.

<sub>Apple M3, 8 GB, macOS 27, files in the operating system's cache; medians of five reads, each opening the file. The [benchmarks page](https://github.com/bijective-systems-org/gamut/blob/main/docs/benchmarks.md) has every number, the method and the scripts to repeat it.</sub>

## Install

| Language | Install |
|---|---|
| Python 3.10 or later | `pip install gamut-format` |
| MATLAB | `build_mex(core)` once in the `matlab` folder of a checkout |
| Julia 1.9 or later | `Pkg.add(url="https://github.com/bijective-systems-org/gamut", subdir="julia")` |
| C and C++ | CMake build and install, then `find_package(gamut)` |

The Python wheels for macOS, Linux and Windows contain the core with HDF5
linked in. MATLAB and Julia use the same core: the wheel's
(`gamut.library_path()` prints where it is) or one built with CMake.
Until version 1 is on PyPI, run `pip install .` in a checkout.
[Installing](https://github.com/bijective-systems-org/gamut/blob/main/docs/install.md) has the details for each language.

## Documentation

The [guide](https://github.com/bijective-systems-org/gamut/blob/main/docs/guide/README.md) has one short page per concept, each
running one script from `examples/`. The
[specification](https://github.com/bijective-systems-org/gamut/blob/main/SPEC.md) defines the format for anyone writing another
implementation, and [how it compares](https://github.com/bijective-systems-org/gamut/blob/main/docs/comparison.md) sets Gamut
beside VTK, CGNS, Exodus, netCDF-CF and Zarr.

Before version 1 the format was called mestra. Its files (`mestra/0`) are
refused with their version named; its 0.1 releases stay on PyPI under that
name.

## License

[Apache 2.0](https://github.com/bijective-systems-org/gamut/blob/main/LICENSE). Made by [Bijective Systems](https://github.com/bijective-systems-org).
If you use Gamut in published work, please cite it ([CITATION.cff](https://github.com/bijective-systems-org/gamut/blob/main/CITATION.cff)).

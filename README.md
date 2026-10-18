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

Gamut is a file format for parametric simulation studies: many runs of one
simulation over its inputs. A file holds the run table (each run's inputs,
results and status), the mesh, and every field, with the units of every
number. Files are HDF5 laid out as netCDF-4, and one C++ core reads and
writes them for Python, MATLAB, Julia and C.

## What it does

| | |
|---|---|
| Languages | Python, MATLAB, Julia and C call one C++ core, so a query returns the same values in each, and any of them reads a file another wrote. h5py, xarray and the netCDF tools read the files without Gamut. |
| Units | Every parameter, result, field and constant declares its units (`Pa`, `m s-1`, `degree`); a file without them is refused when written. Python converts on read and write ([reading parts](https://github.com/bijective-systems-org/gamut/blob/main/docs/guide/08-reading-parts.md)). |
| Run metadata | Parameters are marked as design inputs, operating conditions or time. Labels record a run's status, fidelity, solver or any other category, and a split records which rows are for training and which for testing. A file can name the group a fair test must hold out whole, such as one shape of a family ([run tables](https://github.com/bijective-systems-org/gamut/blob/main/docs/guide/01-run-tables.md)). |
| Uncertainty and gradients | A standard deviation, a quantile or a derivative is stored as a result that names the result it describes, so a plotting or training script finds it without naming conventions ([uncertainty](https://github.com/bijective-systems-org/gamut/blob/main/docs/guide/06-uncertainty-and-gradients.md)). |
| Meshes | One mesh for every run, with each field stored as one block of runs × nodes; one geometry per member of a family of shapes on one topology; or a different mesh per run ([one mesh](https://github.com/bijective-systems-org/gamut/blob/main/docs/guide/02-one-mesh.md), [families](https://github.com/bijective-systems-org/gamut/blob/main/docs/guide/03-geometry-families.md)). |
| Model files | A fitted model is a file of the same shape with no runs, holding the model's numbers but no code. Evaluating it on new inputs gives an ordinary study ([models](https://github.com/bijective-systems-org/gamut/blob/main/docs/guide/07-models.md)). |
| Reads | Runs are chosen by condition (`mach > 0.7 and status == converged`), and one run, one region or one node across every run is read without the rest of the file. HDF5 handles one call at a time, so Gamut fetches compressed chunks through it and decompresses them on several threads. |
| Checks | `gamut validate` tests a file against the 34 numbered rules of the [specification](https://github.com/bijective-systems-org/gamut/blob/main/SPEC.md). A corpus of 64 valid, broken and hostile files runs against all four languages in CI, and readers check sizes before allocating memory and never follow links ([files from outside](https://github.com/bijective-systems-org/gamut/blob/main/docs/security.md)). |

## Example

Nine runs of potential flow past a cylinder, each written as it finishes,
then the pressure at the top of the cylinder read in the runs with
circulation above 2. `points`, `cells`
and `solve` stand for your mesh and your solver; each example in
[`examples/`](https://github.com/bijective-systems-org/gamut/blob/main/examples) is the complete program.

### Python

```python
with gamut.create("cylinder.gamut", writer="example sweep", mesh="shared", per="fixed",
                   coordinates={"units": "m", "axes": 2},
                   parameters={"gamma": {"units": "m2 s-1", "role": "design"}},
                   fields={"cp": {"units": "1", "at": "node"}}) as study:
    study.set_mesh(points, cells)
    for gamma in np.linspace(0.0, 4.0, 9):
        study.add_run({"gamma": gamma}, fields={"cp": solve(gamma)})

with gamut.open("cylinder.gamut") as study:
    rows = study.select("gamma > 2")
    cp = study.get_field("cp", rows=rows, nodes=[12])     # runs x nodes
```

### MATLAB

```matlab
study = gamut.create('cylinder.gamut', 'writer', 'example sweep', 'mesh', 'shared', 'per', 'fixed', ...
    'coordinates', struct('units', 'm', 'axes', 2), ...
    'parameters', struct('gamma', struct('units', 'm2 s-1', 'role', 'design')), ...
    'fields', struct('cp', struct('units', '1', 'at', 'node')));
study.setMesh(points, cells);
for gamma = linspace(0, 4, 9)
    study.addRun(struct('gamma', gamma), 'fields', struct('cp', solve(gamma)));
end
study.close();

study = gamut.open('cylinder.gamut');
rows = study.select('gamma > 2');
cp = study.getField('cp', 'rows', rows, 'nodes', 13);           % runs x nodes, from 1
study.close();
```

### Julia

```julia
Gamut.create("cylinder.gamut"; writer="example sweep", mesh="shared", per="fixed",
              coordinates=(units="m", axes=2),
              parameters=Dict("gamma" => (units="m2 s-1", role="design")),
              fields=Dict("cp" => (units="1", at="node"))) do study
    Gamut.set_mesh!(study; points, cells)
    for gamma in range(0, 4; length=9)
        Gamut.add_run!(study, Dict("gamma" => gamma); fields=Dict("cp" => solve(gamma)))
    end
end

cp = Gamut.open("cylinder.gamut") do study
    rows = Gamut.select(study, "gamma > 2")
    Gamut.get_field(study, "cp"; rows, nodes=[13])           # runs × nodes, from 1
end
```

### C

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
for (int run = 0; run < 9; ++run) {
  const double gamma = 0.5 * run;
  solve(gamma, cp);
  CHECK(gamut_batch_begin(f, 1, &err));             /* one run, all or nothing */
  CHECK(gamut_batch_values(f, "gamma", GAMUT_FLOAT64, &gamma, 1, &err));
  CHECK(gamut_batch_values(f, "cp", GAMUT_FLOAT64, cp, N_NODES, &err));
  CHECK(gamut_batch_commit(f, NULL, &err));
}
CHECK(gamut_close(f, &err));

CHECK(gamut_open("cylinder.gamut", &f, &err));
int64_t rows[9], n = 0, node = 12;
CHECK(gamut_select(f, "gamma > 2", rows, 9, &n, &err));
const gamut_sel chosen = {GAMUT_SEL_INDEX, 0, 0, rows, n};
const gamut_sel one_node = {GAMUT_SEL_INDEX, 0, 0, &node, 1};
double values[9];
CHECK(gamut_read(f, "cp", &chosen, &one_node, GAMUT_FLOAT64, values, sizeof values, &err));
```

All four print the same line, and any of them reads a file another wrote:

```text
cp on top of the cylinder where gamma > 2: -1.57 -1.32 -1.08 -0.86
```

MATLAB and Julia count positions from 1, so node 12 in Python and C is node 13 in
MATLAB and Julia.

## Performance

<p align="center">
  <img src="https://raw.githubusercontent.com/bijective-systems-org/gamut/main/docs/assets/bench-summary.svg" alt="Size on disk and three read times for one study stored as Gamut, HDF5 with a group per run, netCDF-4, Zarr and VTK files." width="760">
</p>

Measured on an Apple M3 with the files in the operating system's cache.
Gamut is about the size of netCDF-4 and Zarr and a sixth of the VTK files.
Its chunks are laid out for reading whole runs, so one node across every
run takes 124 ms, slower than netCDF-4 (54 ms) and Zarr (4 ms); with four
threads it takes 38 ms. On a second study, with 177,000-node meshes, one
run reads in 15 ms against 124 ms from its VTK file. The
[benchmarks page](https://github.com/bijective-systems-org/gamut/blob/main/docs/benchmarks.md) has every number, the method and
the scripts to repeat it.

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

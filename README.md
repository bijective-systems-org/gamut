<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/bijective-systems-org/gamut/main/docs/assets/logo-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/bijective-systems-org/gamut/main/docs/assets/logo.svg">
    <img src="https://raw.githubusercontent.com/bijective-systems-org/gamut/main/docs/assets/logo-any.svg" alt="Gamut" width="240">
  </picture>
</p>

<p align="center">
An open file format for parametric simulation studies,<br>
with libraries for Python, MATLAB, Julia, C++ and C.
</p>

<p align="center">
  <a href="https://github.com/bijective-systems-org/gamut/actions/workflows/ci.yml"><img src="https://github.com/bijective-systems-org/gamut/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI"></a>
</p>

---

Gamut is a file format for parametric simulation studies: the hundreds or
thousands of CFD or FEA runs behind a design sweep, an aerodynamic
database or a surrogate model. One file holds the run table, each run's
inputs, results and status, and, when the runs have a mesh, the mesh and
every field on it, all with units. Python, MATLAB, Julia and C++ read and
write it with the same calls. Files are HDF5 laid out as netCDF-4, so h5py,
xarray and the netCDF tools open them too, and a published specification
says what every array in them means.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/bijective-systems-org/gamut/main/docs/assets/hero-dark.svg">
    <img src="https://raw.githubusercontent.com/bijective-systems-org/gamut/main/docs/assets/hero.svg" alt="A study file laid open: an XFOIL sweep of a NACA 4412 section, 363 runs on one shared mesh of 160 nodes. Each table row is one run: its inputs, status, train or test split, lift with its spread over transition criteria, drag and moment, continued by its pressure coefficient at every node. A failed run keeps its inputs with no results. A select call shades the 40 runs it picks." width="760">
  </picture>
</p>

## Example

Nine runs of potential flow past a cylinder on one mesh: eight written as
a sweep, a ninth added after reopening the file, then the pressure at one
node read back from every run. `points`, `cells` and `solve` stand for
your mesh and your solver, and the complete programs are in
[`examples/`](https://github.com/bijective-systems-org/gamut/blob/main/examples).

Python

```python
with gamut.create("cylinder.gamut", writer="example sweep", mesh="shared", per="fixed",
                   coordinates={"units": "m", "axes": 2},
                   parameters={"gamma": {"units": "m2 s-1", "role": "design"}},
                   fields={"cp": {"units": "1", "at": "node"}}) as study:
    study.set_mesh(points, cells)
    for gamma in np.linspace(0.0, 3.5, 8):
        study.add_run({"gamma": gamma}, fields={"cp": solve(gamma)})

with gamut.open("cylinder.gamut", mode="a") as study:
    study.add_run({"gamma": 4.0}, fields={"cp": solve(4.0)})

with gamut.open("cylinder.gamut") as study:
    cp = study.get_field("cp", nodes=[12])                 # runs x nodes
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

study = gamut.open('cylinder.gamut', 'mode', 'a');
study.addRun(struct('gamma', 4), 'fields', struct('cp', solve(4)));
study.close();

study = gamut.open('cylinder.gamut');
cp = study.getField('cp', 'nodes', 13);                         % runs x nodes, from 1
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

Gamut.open("cylinder.gamut"; mode="a") do study
    Gamut.add_run!(study, Dict("gamma" => 4.0); fields=Dict("cp" => solve(4.0)))
end

cp = Gamut.open("cylinder.gamut") do study
    Gamut.get_field(study, "cp"; nodes=[13])                 # runs × nodes, from 1
end
```

C++

```cpp
auto study = gamut::create("cylinder.gamut", "example sweep", "shared", "fixed");
study.declare_coordinates("m", 2);
study.declare_parameter("gamma", "design", "m2 s-1");
study.declare_field("cp", "node", "1");
study.set_mesh(points, cells);
for (double gamma = 0.0; gamma < 3.75; gamma += 0.5)
  study.add_run({{"gamma", gamma}}, {{"cp", solve(gamma)}});
study.close();

study = gamut::open("cylinder.gamut", "a");
study.add_run({{"gamma", 4.0}}, {{"cp", solve(4.0)}});
study.close();

study = gamut::open("cylinder.gamut");
auto cp = study.get_field("cp", gamut::all, {12});    // runs x nodes
```

All four print the same values:

```text
cp at the top of the cylinder, run by run: -3.00 -2.69 -2.39 -2.10 -1.83 -1.57 -1.32 -1.08 -0.86
```

MATLAB and Julia count positions from 1, so node 12 in Python and C++ is
node 13 in MATLAB and Julia.

## What you can do with it

| | |
|---|---|
| Use one file everywhere | Python, MATLAB, Julia, C++ and C call one core, so a query returns the same values in each, and each reads what another wrote. |
| Read only what you need | Choose runs by condition (`mach > 0.7 and status == converged`) and nodes by zone. On a shared mesh, one region of every run or one node across thousands of runs is a single read, and Python can convert values to the units you ask for ([reading parts](https://github.com/bijective-systems-org/gamut/blob/main/docs/guide/08-reading-parts.md)). |
| Train models on it | Each field on a shared mesh is one block of runs × nodes (or cells). Labels record status, fidelity or solver, a split says which rows are for training and which for testing, and a file can name the group a fair test must hold out whole. Standard deviations, quantiles and derivatives are stored beside the results they describe ([run tables](https://github.com/bijective-systems-org/gamut/blob/main/docs/guide/01-run-tables.md), [uncertainty](https://github.com/bijective-systems-org/gamut/blob/main/docs/guide/06-uncertainty-and-gradients.md)). |
| Share fitted models | A model is a file in the same format with no runs and no code inside. Evaluating it on new inputs gives an ordinary study; a model type of your own is registered by the software that defines it ([models](https://github.com/bijective-systems-org/gamut/blob/main/docs/guide/07-models.md)). |
| Hold tables, families and time series | A table of runs with no mesh, one mesh for every run, one geometry per member of a family of shapes on one topology, a mesh per run, or transient runs with a row per saved step ([families](https://github.com/bijective-systems-org/gamut/blob/main/docs/guide/03-geometry-families.md), [time series](https://github.com/bijective-systems-org/gamut/blob/main/docs/guide/05-time-series.md)). |
| Check what you receive | Writers require units on parameters, results, constants and coordinates, and `gamut validate` checks the 35 numbered rules of the [specification](https://github.com/bijective-systems-org/gamut/blob/main/SPEC.md). A corpus of 65 valid, broken and hostile files runs in CI through the Python, MATLAB and Julia libraries and the C interface under them, and readers check sizes before allocating memory and never follow links ([files from outside](https://github.com/bijective-systems-org/gamut/blob/main/docs/security.md)). |

## Performance

Gamut stores the study's meaning alongside compressed arrays: inputs,
units, run status and geometry relationships, with the same study
interface across languages. It builds on HDF5/netCDF-4; the benchmarks
measure the cost of those conventions and operations alongside native
simulation formats and direct storage access.

<p align="center">
  <img src="https://raw.githubusercontent.com/bijective-systems-org/gamut/main/docs/assets/bench-study.svg" alt="File size and read times of Exodus II, CGNS and PhysicsNeMo-Mesh relative to Gamut, for a triangulated capsule geometry family and an XFOIL airfoil sweep. Every format uses the same mesh within each dataset." width="760">
</p>

Gamut preserves the capsule's quadrilateral cells directly.
**PhysicsNeMo-Mesh requires simplices, so its capsule case needs conversion
to triangles.** The chart uses that same converted mesh for every format;
the original quad results remain on the benchmarks page.

On the triangulated capsule family, Gamut and compressed Exodus occupy
about the same space. Gamut is smaller and reads one run faster than PMSH;
four decompression threads also make the reads across all runs competitive.
PMSH writes faster. On the smaller airfoil sweep, PMSH reads faster, while
Gamut is smaller. Direct h5py reads of the same Gamut arrays show similar
bulk decoding time, with less fixed overhead for small reads.
The [benchmarks](https://github.com/bijective-systems-org/gamut/blob/main/docs/benchmarks.md)
include the full timings, settings, payload checks and workloads where
another approach is faster, plus the earlier VTK, VTKHDF, Zarr and NumPy
comparisons.

The [four-language example above](#example) shows the same write, append
and read returning the same values. The [reading-parts example](https://github.com/bijective-systems-org/gamut/blob/main/docs/guide/08-reading-parts.md)
selects converged runs and reads a named surface region in specified
units. The format supplies the study conventions and operations that a
custom array layout leaves each producer to maintain.

<sub>Apple M3, 8 GB; warm-cache medians of five, each opening and closing the file. Native copies include the run-table/schema companions; the condition query reads those companions for Exodus, CGNS and PMSH. Exodus uses gzip level 1 and shuffle; CGNS uses native uncompressed defaults; PMSH uses CPU memory mapping. Triangulation retains nodal values without a solver rerun. Full method, versions and source commits are on the benchmarks page.</sub>

## Install

| Language | Install |
|---|---|
| Python 3.10 or later | `pip install gamut-format` |
| MATLAB | `build_mex(core)` once in the `matlab` folder of a checkout |
| Julia 1.9 or later | `Pkg.add(url="https://github.com/bijective-systems-org/gamut", subdir="julia")` |
| C++ and C | CMake build and install, then `find_package(gamut)`; include `gamut/gamut.hpp` (C++17) or `gamut/gamut.h` (C) |

The Python wheels for macOS, Linux and Windows contain the core with HDF5
linked in. MATLAB and Julia use the same core: the wheel's
(`gamut.library_path()` prints where it is) or one built with CMake.
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

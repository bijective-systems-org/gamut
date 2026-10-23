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
write it with the same calls. A model fitted to the runs is saved the same
way, as plain numbers with no code, and evaluated on new inputs. Files are
HDF5 laid out as netCDF-4, so h5py, xarray and the netCDF tools open them
too, and a published specification says what every array in them means.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/bijective-systems-org/gamut/main/docs/assets/hero-dark.svg">
    <img src="https://raw.githubusercontent.com/bijective-systems-org/gamut/main/docs/assets/hero.svg" alt="A study file laid open: an XFOIL sweep of a NACA 4412 section, 363 runs on one shared mesh of 160 nodes. Each table row is one run: its inputs, status, train or test split, lift with its spread over transition criteria, drag and moment, continued by its pressure coefficient at every node. A failed run keeps its inputs with no results. A select call shades the 40 runs it picks." width="760">
  </picture>
</p>

## Example

A sweep of a wing's angle of attack: six runs written, a seventh added
later, and the lift of the runs that converged read back, as a model
fitted to the study would read it. `solve` stands for your solver; the
complete programs are in [`examples/`](https://github.com/bijective-systems-org/gamut/blob/main/examples).

Python

```python
with gamut.create("sweep.gamut", writer="example sweep",
                   parameters={"alpha": {"units": "degree", "role": "condition"}},
                   labels={"status": {"role": "status", "categories": ["converged", "failed"]}},
                   scalars={"cl": "1"}) as study:
    for alpha in range(0, 11, 2):
        study.add_run({"alpha": alpha, "status": "converged", "cl": solve(alpha)})

with gamut.open("sweep.gamut", mode="a") as study:
    study.add_run({"alpha": 12, "status": "failed"})

with gamut.open("sweep.gamut") as study:
    cl = study.get_scalar("cl", rows=study.select("status == converged"))
```

MATLAB

```matlab
study = gamut.create('sweep.gamut', 'writer', 'example sweep', ...
    'parameters', struct('alpha', struct('units', 'degree', 'role', 'condition')), ...
    'labels', struct('status', struct('role', 'status', 'categories', {{'converged', 'failed'}})), ...
    'scalars', struct('cl', '1'));
for alpha = 0:2:10
    study.addRun(struct('alpha', alpha, 'status', 'converged', 'cl', solve(alpha)));
end
study.close();

study = gamut.open('sweep.gamut', 'mode', 'a');
study.addRun(struct('alpha', 12, 'status', 'failed'));
study.close();

study = gamut.open('sweep.gamut');
cl = study.getScalar('cl', 'rows', study.select('status == converged'));
study.close();
```

Julia

```julia
Gamut.create("sweep.gamut"; writer="example sweep",
              parameters=Dict("alpha" => (units="degree", role="condition")),
              labels=Dict("status" => (role="status", categories=["converged", "failed"])),
              scalars=Dict("cl" => "1")) do study
    for alpha in 0.0:2.0:10.0
        Gamut.add_run!(study, Dict("alpha" => alpha, "status" => "converged", "cl" => solve(alpha)))
    end
end

Gamut.open("sweep.gamut"; mode="a") do study
    Gamut.add_run!(study, Dict("alpha" => 12.0, "status" => "failed"))
end

cl = Gamut.open("sweep.gamut") do study
    Gamut.get_scalar(study, "cl"; rows=Gamut.select(study, "status == converged"))
end
```

C++

```cpp
auto study = gamut::create("sweep.gamut", "example sweep");
study.declare_parameter("alpha", "condition", "degree");
study.declare_label("status", "status", {"converged", "failed"});
study.declare_scalar("cl", "1");
for (double alpha = 0.0; alpha <= 10.0; alpha += 2.0)
  study.add_run({{"alpha", alpha}, {"status", "converged"}, {"cl", solve(alpha)}});
study.close();

study = gamut::open("sweep.gamut", "a");
study.add_run({{"alpha", 12.0}, {"status", "failed"}});
study.close();

study = gamut::open("sweep.gamut");
const std::vector<double> cl = study.get_scalar("cl", study.select("status == converged"));
```

All four print the same line:

```text
lift of the runs that converged: 0.00 0.22 0.44 0.66 0.88 1.10
```

Every name is declared once, with its units and role, and each run then
gives its values; the failed run has no lift, so it is stored as missing.
`select` returns the positions of the rows it picks, counted from 0 in
Python and C++ and from 1 in MATLAB and Julia.

### With a mesh

When every run has the same mesh, the file stores the mesh once and each
field as one block of runs × nodes, so one run, one region of every run or
one node across all of them is a single read. The declaration adds the
mesh, its coordinates and its zones, and the fields:

```python
with gamut.create("cylinder.gamut", writer="example sweep", mesh="shared", per="fixed",
                   coordinates={"units": "m", "axes": 2},
                   parameters={"gamma": {"units": "m2 s-1", "role": "design"}},
                   mesh_labels={"surface": {"at": "node", "categories": ["field", "wall"]}},
                   fields={"cp": {"units": "1", "at": "node"}}) as study:
    study.set_mesh(points, cells, labels={"surface": surface})
```

Each run then brings its fields, `study.add_run({"gamma": gamma},
fields={"cp": cp})`, and `study.get_field("cp")` returns runs × nodes
([one mesh](https://github.com/bijective-systems-org/gamut/blob/main/docs/guide/02-one-mesh.md)).

### A model in a file

A model fitted to the sweep is saved in the same format: a file with no
runs, whose parameter keeps the range of angles the model was fitted on
and whose result names the model that computes it. Here a quadratic is
fitted in Python to the angles and lifts of the runs that converged,
`alpha` and `cl`, and saved:

```python
with gamut.create_model("lift_model.gamut", writer="example fit", trained_on=[sweep_id],
                         parameters={"alpha": {"units": "degree", "lower": 0.0, "upper": 10.0}},
                         scalars={"cl": {"units": "1", "model": "fit", "output": "cl"}}) as model:
    model.add_model("fit", Polynomial(np.polyfit(alpha, cl, 2)), inputs=["alpha"])
```

MATLAB evaluates the file with no Python involved:

```matlab
gamut.registerModelType('Polynomial');
answer = gamut.evaluate('lift_model.gamut', struct('alpha', [2.2; 7.9]));
lift = answer.getScalar('cl');
answer.close();
```

```text
the model's lift at 2.2 and 7.9 degrees: 0.24 0.87
```

The file holds the quadratic's three coefficients, not code. `Polynomial`
is the model's type: a class of a few lines in each language that saves
the coefficients and computes with them. `trained_on` records the sweep's
`file_id`. The answer is an ordinary study file of two runs, and
`gamut.evaluate` in Python gives the same
([models](https://github.com/bijective-systems-org/gamut/blob/main/docs/guide/07-models.md)).

The [guide](https://github.com/bijective-systems-org/gamut/blob/main/docs/guide/README.md)
starts from these three and goes on to families of shapes on one mesh, a
mesh per run, time series and uncertainty, a page each.

## What you can do with it

| | |
|---|---|
| Use one file everywhere | Python, MATLAB, Julia, C++ and C call one core, so a query returns the same values in each, and each reads what another wrote. |
| Read only what you need | Choose runs by condition (`mach > 0.7 and status == converged`) and nodes by zone. On a shared mesh, one region of every run or one node across thousands of runs is a single read, and Python can convert values to the units you ask for ([reading parts](https://github.com/bijective-systems-org/gamut/blob/main/docs/guide/08-reading-parts.md)). |
| Train models on it | Each field on a shared mesh is one block of runs × nodes (or cells). Labels record status, fidelity or solver, a split says which rows are for training and which for testing, and a file can name the group a fair test must hold out whole ([families](https://github.com/bijective-systems-org/gamut/blob/main/docs/guide/03-geometry-families.md)). Standard deviations, quantiles and derivatives are stored beside the results they describe ([run tables](https://github.com/bijective-systems-org/gamut/blob/main/docs/guide/01-run-tables.md), [uncertainty](https://github.com/bijective-systems-org/gamut/blob/main/docs/guide/06-uncertainty-and-gradients.md)). |
| Share fitted models | A model is a file in the same format with no runs and no code inside: its numbers, the units and fitted range of its inputs, and the study it came from. A model type of your own is a short class registered in Python or MATLAB; the built-in nearest-run model evaluates in every language. Evaluating gives an ordinary study ([models](https://github.com/bijective-systems-org/gamut/blob/main/docs/guide/07-models.md)). |
| Hold tables, families and time series | A table of runs with no mesh, one mesh for every run, one geometry per member of a family of shapes on one topology, a mesh per run, or transient runs with a row per saved step ([families](https://github.com/bijective-systems-org/gamut/blob/main/docs/guide/03-geometry-families.md), [time series](https://github.com/bijective-systems-org/gamut/blob/main/docs/guide/05-time-series.md)). |
| Check what you receive | Writers require units on parameters, results, constants and coordinates, and `gamut validate` checks the 35 numbered rules of the [specification](https://github.com/bijective-systems-org/gamut/blob/main/SPEC.md). A corpus of 67 valid, broken and hostile files runs in CI through the Python, MATLAB and Julia libraries and the C interface under them, and readers check sizes before allocating memory and never follow links ([files from outside](https://github.com/bijective-systems-org/gamut/blob/main/docs/security.md)). |

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
| MATLAB R2023b or later | open `Gamut.mltbx` from the [latest release](https://github.com/bijective-systems-org/gamut/releases/latest) |
| Julia 1.9 or later | `Pkg.add(url="https://github.com/bijective-systems-org/gamut", subdir="julia", rev="v1.1.0")` |
| C++ and C | CMake build and install, then `find_package(gamut)`; include `gamut/gamut.hpp` (C++17) or `gamut/gamut.h` (C) |

The Python wheels and the MATLAB toolbox carry the core with HDF5 linked
in, for macOS, Linux and Windows, and need no compiler. Julia, C and C++
use the same core: each release's `gamut-core-<version>-<platform>`
archive, the wheel's (`gamut.library_path()` prints where it is), or one
built with CMake.
[Installing](https://github.com/bijective-systems-org/gamut/blob/main/docs/install.md) has the details for each language.

## Documentation

The [guide](https://github.com/bijective-systems-org/gamut/blob/main/docs/guide/README.md) has one short page per concept, each
running one script from `examples/`. The
[specification](https://github.com/bijective-systems-org/gamut/blob/main/SPEC.md) defines the format for anyone writing another
implementation, and [how it compares](https://github.com/bijective-systems-org/gamut/blob/main/docs/comparison.md) sets Gamut
beside VTK, CGNS, Exodus, netCDF-CF and Zarr.

The format is versioned, and every file names its version (`gamut/1`).
Within version 1 a change only adds, and a reader skips what it does not
know, so a file written today stays readable; a reader refuses a later
major version by name ([versions](https://github.com/bijective-systems-org/gamut/blob/main/SPEC.md#17-versions-and-additions)).
Before version 1 the format was called mestra. Its files (`mestra/0`) are
refused with their version named; its 0.1 releases stay on PyPI under that
name.

## License

[Apache 2.0](https://github.com/bijective-systems-org/gamut/blob/main/LICENSE). Made by [Bijective Systems](https://github.com/bijective-systems-org).
If you use Gamut in published work, please cite it ([CITATION.cff](https://github.com/bijective-systems-org/gamut/blob/main/CITATION.cff)).

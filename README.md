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

A parametric study usually ends as a folder of solver outputs, a spreadsheet
of inputs and a script that knows how to join them. Gamut stores the study as
one compressed file: the runs and their inputs, the results, the mesh and its
fields, with units, roles and statuses written down. Anyone with the file can
check the study or train a model on it, without the script.

<p align="center">
  <img src="https://raw.githubusercontent.com/bijective-systems-org/gamut/main/docs/assets/one-study-one-file.svg" alt="A folder of VTK files, a parameters table and a joining script become one file holding the run table, the mesh, and every field as one block of runs by nodes." width="760">
</p>

## Performance

Measured on two real studies, against the folder of VTK files each came as:

| | Gamut | VTK files |
|---|---:|---:|
| Size of 1,364 runs of a capsule family | **66 MB** | 419 MB |
| Writing those runs | **1.2 s** | 10.6 s |
| Reading one node across all 1,364 runs | **124 ms** | 4.9 s |
| Reading one run of a 177,000-node airfoil study | **15 ms** | 124 ms |

Choosing runs by a condition and reading them takes about a millisecond,
sixty times faster than HDF5 stored a run per group. Gamut files are about
the size of netCDF and Zarr files. HDF5 written a run at a time reads one
small run faster, and Zarr's default chunks read one node across many runs
faster. The [benchmarks page](https://github.com/bijective-systems-org/gamut/blob/main/docs/benchmarks.md)
has the full comparison and how it was measured.

## Example

A sweep written one run at a time, as a solver finishes each, then read by
condition (`points`, `cells` and `solve` stand for your mesh and your
solver):

```python
with gamut.create("cylinder.gamut", writer="my sweep", mesh="shared", per="fixed",
                   coordinates={"units": "m", "axes": 2},
                   parameters={"gamma": {"units": "m2 s-1", "role": "design"}},
                   fields={"cp": {"units": "1", "at": "node"}}) as study:
    study.set_mesh(points, cells)                          # once: every run shares it
    for gamma in np.linspace(0.0, 4.0, 9):                 # one run at a time, as a solver finishes
        study.add_run({"gamma": gamma}, fields={"cp": solve(gamma)})

with gamut.open("cylinder.gamut") as study:
    rows = study.select("gamma > 2")
    cp = study.get_field("cp", rows=rows, nodes=[12])     # runs x nodes
```

## MATLAB, Julia and C

The four libraries share one C++ core, so a query returns the same values in
every language.

**MATLAB**

```matlab
study = gamut.open('cylinder.gamut');
rows = study.select('gamma > 2');
cp = study.getField('cp', 'rows', rows, 'nodes', 13);           % runs x nodes, from 1
```

**Julia**

```julia
study = Gamut.open("cylinder.gamut")
rows = Gamut.select(study, "gamma > 2")
cp = Gamut.get_field(study, "cp"; rows, nodes=[13])        # runs × nodes, from 1
```

**C**

```c
CHECK(gamut_open("cylinder.gamut", &f, &err));
int64_t rows[9], n = 0, node = 12;
CHECK(gamut_select(f, "gamma > 2", rows, 9, &n, &err));
const gamut_sel chosen = {GAMUT_SEL_INDEX, 0, 0, rows, n};
const gamut_sel one_node = {GAMUT_SEL_INDEX, 0, 0, &node, 1};
double values[9];
CHECK(gamut_read(f, "cp", &chosen, &one_node, GAMUT_FLOAT64, values, sizeof values, &err));
```

All four print:

```text
cp on top of the cylinder where gamma > 2: -1.57 -1.32 -1.08 -0.86
```

## Units

Every parameter, result, field and constant declares its units, in the
UDUNITS grammar that netCDF-CF uses (`Pa`, `m s-1`, `kg m-3`, `degree`).
Missing or unparseable units are refused when a file is written and reported
by `gamut validate` in a file from elsewhere. Python converts on read:

```python
p_wall = study.get_field("p", rows=rows, nodes=on_wall, units="kPa")
```

It converts on write too: a value given as `(72, "km/h")` is stored in the
`m s-1` the file declares. MATLAB, Julia and C return values in the units
they were stored in, which `describe` names.

## What a file records

Besides the values, a file records what they mean. Parameters have a role
(design input, operating condition or time). A status label marks the runs
that converged, so training can skip the rest, and a split can publish the
train and test sets. The file can also name the group a fair test must hold
out whole, such as one geometry of a family, and a split that mixes it is
reported. The mesh can be shared by every run, given per member of a family
of shapes on one topology, or differ from run to run. A fitted model is
stored as a file of the same shape with no rows, and evaluating it produces
an ordinary study.

Files are HDF5 laid out as netCDF-4, so h5py, xarray and the netCDF tools
read them without this package, and `gamut-vtk` converts a study to and from
VTK files. `gamut validate` reports every rule a file breaks. The libraries
check sizes before allocating memory and never follow links, which matters
for files from outside ([security](https://github.com/bijective-systems-org/gamut/blob/main/docs/security.md)),
and a shared corpus of valid, broken and hostile files holds all four to the
specification. The `gamut` command (`info`, `validate`, `build`, `append`,
`get`) prints JSON with `--json`.

## Install

```bash
pip install gamut-format            # Python 3.10 or later; wheels for macOS, Linux and Windows
pip install "gamut-format[vtk]"     # with VTK import and export
```

Until version 1 is on PyPI, install from a checkout with `pip install .`
instead. MATLAB, Julia and C or C++: see
[installing](https://github.com/bijective-systems-org/gamut/blob/main/docs/install.md).

## Documentation

[Start here](https://github.com/bijective-systems-org/gamut/blob/main/docs/start-here.md)
takes you from installing to your own studies. The
[guide](https://github.com/bijective-systems-org/gamut/blob/main/docs/guide/README.md)
has one page per concept, each with a script you can run. The
[specification](https://github.com/bijective-systems-org/gamut/blob/main/SPEC.md)
defines the format for anyone writing another implementation, and
[how it compares](https://github.com/bijective-systems-org/gamut/blob/main/docs/comparison.md)
sets it beside VTK, CGNS, Exodus, netCDF-CF and Zarr.

## Status

Version 1 of the format (`gamut/1`) is specified and implemented: the C++
core, Python, MATLAB and Julia, the validator, the command line and VTK
conversion. Before version 1 the format was called mestra; its 0.1 releases
stay on PyPI under that name.

## License

[Apache 2.0](https://github.com/bijective-systems-org/gamut/blob/main/LICENSE). Made by [Bijective Systems](https://github.com/bijective-systems-org).
If you use Gamut in published work, please cite it ([CITATION.cff](https://github.com/bijective-systems-org/gamut/blob/main/CITATION.cff)).

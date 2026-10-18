<p align="center">
  <img src="https://raw.githubusercontent.com/bijective-systems-org/mestra/main/docs/assets/logo.svg" alt="mestra" width="240">
</p>

<p align="center">
An open file format for simulation studies: every run, the mesh it ran on,<br>
and what each number means, in one file that reads the same way from Python,
MATLAB, Julia and C.
</p>

---

A parametric study usually ends as a folder of solver outputs, a spreadsheet
of inputs and a script that knows how to join them. mestra keeps the runs,
their inputs and results, the mesh and its fields in one compressed file,
with units, roles and statuses written down, so the study can be shared,
checked and used to train models without the script.

<p align="center">
  <img src="https://raw.githubusercontent.com/bijective-systems-org/mestra/main/docs/assets/one-study-one-file.svg" alt="A folder of VTK files, a parameters table and a joining script become one file holding the run table, the mesh, and every field as one block of runs by nodes." width="760">
</p>

## In a few lines

```python
import mestra

with mestra.create("sweep.mes", writer="my solver", mesh="shared", per="fixed",
                   coordinates={"units": "m", "axes": 3},
                   parameters={"mach": "1", "alpha": "degree"},
                   fields={"p": {"units": "Pa", "at": "node"}}) as study:
    study.set_mesh(points, cells)                       # once: every run shares it
    for mach, alpha, pressure in runs:                  # from your solver
        study.add_run({"mach": mach, "alpha": alpha}, fields={"p": pressure})

with mestra.open("sweep.mes") as study:
    fast = study.select("mach > 0.7")
    p = study.get_field("p", rows=fast)                 # runs x nodes, in Pa
```

## What it gives you

- **One file per study.** Runs, inputs, results, mesh and fields together,
  compressed, appended to one run at a time as a study grows.
- **Reads by part.** One run, a region of every run, or one node across
  thousands of runs, each one call that returns only what was asked for.
- **Meaning that travels with the numbers.** Units on every value, checked;
  which runs failed; which rows share a geometry or belong to one transient
  run; uncertainty and gradients beside the values they describe.
- **Models in the same terms as the data.** A fitted surrogate is a file of
  the same shape with no rows, and evaluating it gives an ordinary study.
- **The same answers in every language.** One C++ core behind Python,
  MATLAB, Julia and C, checked against the specification by a shared corpus
  of valid, broken and hostile files.
- **Nothing locked in.** Underneath it is HDF5 laid out as netCDF-4, so
  h5py, xarray and the netCDF tools read it without this package, and one
  command turns a study back into VTK files.

On two real studies, one mestra file was six times and two times smaller
than the folder of VTK files each came as, and read one run, or the runs
meeting a condition, in milliseconds. The [benchmarks](https://github.com/bijective-systems-org/mestra/blob/main/docs/benchmarks.md)
compare it with VTK, HDF5, netCDF and Zarr, including where it is slower.

## Install

```bash
pip install mestra            # Python 3.10 or later; wheels for macOS, Linux and Windows
pip install "mestra[vtk]"     # with VTK import and export
```

Until version 1 is on PyPI, these bring the earlier 0.1 series: install from
a checkout with `pip install .` instead. MATLAB, Julia and C or C++: see
[installing](https://github.com/bijective-systems-org/mestra/blob/main/docs/install.md).

## Where next

- [**Start here**](https://github.com/bijective-systems-org/mestra/blob/main/docs/start-here.md): the first ten minutes, the first day,
  the first week.
- [**Guide**](https://github.com/bijective-systems-org/mestra/blob/main/docs/guide/README.md): one page per concept, each with a
  script you can run.
- [**Specification**](https://github.com/bijective-systems-org/mestra/blob/main/SPEC.md): the format itself, for anyone writing
  another implementation.
- [**How it compares**](https://github.com/bijective-systems-org/mestra/blob/main/docs/comparison.md) with VTK, CGNS, Exodus,
  netCDF-CF and Zarr.

## Status

Version 1 of the format (`mestra/1`) is specified and implemented: the C++
core, Python, MATLAB and Julia, the validator, the command line and VTK
conversion. It is not yet released on PyPI; until it is, install from a
checkout with `pip install .` (see [installing](https://github.com/bijective-systems-org/mestra/blob/main/docs/install.md)).

## License

[Apache 2.0](https://github.com/bijective-systems-org/mestra/blob/main/LICENSE). Made by [Bijective Systems](https://github.com/bijective-systems-org).
If you use mestra in published work, please cite it ([CITATION.cff](https://github.com/bijective-systems-org/mestra/blob/main/CITATION.cff)).

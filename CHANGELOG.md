# Changelog

## 1.0.0 (unreleased)

Version 1 of the format, `gamut/1`, and a new implementation. Before
version 1 the format and its libraries were called mestra (the 0.1 series
on PyPI).

- **The format** ([SPEC.md](SPEC.md)) is redesigned around the study: a run
  table with roles, statuses and splits; a shared mesh whose geometry is
  fixed, per run or per member of a family, or a mesh per run; fields as
  one block of runs × nodes; uncertainty and derivatives as relations;
  model files of the same shape as data. Files of the earlier `mestra/0`
  are refused with a message naming their version.
- **One core.** A C++ core with a C interface implements the format;
  Python, MATLAB and Julia are layers over it, so every language gives the
  same answers. Packages link HDF5 statically, so the core never meets
  another HDF5 in the same process.
- **Python**: `create`, `open`, `append`, `extract`, `write_copy`,
  `validate`, `create_model`, `evaluate`; the `gamut` command line
  (`info`, `validate`, `build`, `append`, `get`); `gamut-vtk` to turn a
  folder of VTK runs into a study and back.
- **MATLAB and Julia**: the same calls in each language's spelling.
- **Untrusted files**: sizes checked before memory is used, links never
  followed, no HDF5 plugins loaded ([security](docs/security.md)).
- **Documentation**: a guide of fourteen pages, each held to a runnable
  example by the tests; [benchmarks](docs/benchmarks.md) on two studies.

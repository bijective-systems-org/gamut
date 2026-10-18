# Changelog

## 1.0.0 (unreleased)

Version 1 of the format, `gamut/1`, and a new implementation. Before
version 1 the format and its libraries were called mestra (the 0.1 series
on PyPI).

The format ([SPEC.md](SPEC.md)) is redesigned around the study: a run
table with roles, statuses and splits; a shared mesh whose geometry is
fixed, per run or per member of a family, or a mesh per run; fields as one
block of runs × nodes; uncertainty and derivatives as relations; and model
files of the same shape as data. Files of the earlier `mestra/0` are
refused with a message naming their version.

A C++ core with a C interface implements the format, and Python, MATLAB
and Julia are layers over it, so every language gives the same answers.
The Python wheels link HDF5 statically, so the core never meets another
HDF5 in the same process.

Python has `create`, `open`, `append`, `extract`, `write_copy`,
`validate`, `create_model` and `evaluate`; the `gamut` command line
(`info`, `validate`, `build`, `append`, `get`); and `gamut-vtk`, which
turns a folder of VTK runs into a study and back. MATLAB, Julia and C++
(the header-only `gamut/gamut.hpp`) have the same calls in each language's
spelling, and C programs use the C interface, `gamut/gamut.h`.

Readers check sizes before using memory, never follow links and load no
HDF5 plugins ([security](docs/security.md)). The guide has fourteen pages,
each held to a runnable example by the tests, and the
[benchmarks](docs/benchmarks.md) cover two studies.

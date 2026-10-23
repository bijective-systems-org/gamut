# Changelog

## Unreleased

Calls from several threads no longer crash. HDF5 keeps state for the whole
process and is built without its thread-safety option, so two threads each
reading its own file could bring it down; every call that reaches a file
now takes its turn. `threads=` remains the way to read one large field
faster.

Appending from C, C++ or MATLAB refuses a file of another major format
version, as reading already did, and does so before opening the file to
write, which leaves it byte for byte as it was.

Messages say more about what to fix. A number left as text (`"4.0"` from
a spreadsheet) is named as such, rather than reported as a missing value;
an illegal name is refused with what a legal one is; W2 counts the rows
of each status and says when no status is named `converged`, the one
name that marks a run as usable; W1 names the group a split divides.

The guide shows how to publish a train and test split, says that only
`converged` marks a run as usable, that a new category name extends a
label's categories, and that unit names are checked only when a read
converts them. Installing covers xarray and Xcode for MATLAB on macOS,
and adds the Julia package at the release tag that matches the wheel.

The validator holds a mesh's computed coordinates to the writer's rules: a
computing model only in a model file whose mesh is per run, which must
name one (E16), and that model existing with its output named (E17). The
writer now also refuses a computing model without an output. An array
holding more values than the validator reads, 2²⁶, is now reported as
unchecked (W11) rather than passed over in silence.

Opening a file takes about a third less time (0.81 to 0.51 ms on the
benchmarks' capsule study): the reader opens each object once, for its
attributes, type and shape together, and leaves the storage settings to the
validator.

## 1.1.0 (2026-10-19)

A model file whose coordinates are computed by a model now evaluates. The
reader looked for the model's name only where coordinates are a group,
and section 10.3 stores them as a zero-length dataset, so evaluation asked
the caller for coordinates instead, and a copy of the file lost which
model computes them. The format is unchanged.

`study.model_numbers(id)` reads a model's stored numbers back as the
dictionary its `save` gave, whether or not its type is registered:
`modelNumbers` in MATLAB and `Gamut.model_numbers` in Julia. C programs
already had `gamut_model_numbers`.

## 1.0.0 (2026-10-18)

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

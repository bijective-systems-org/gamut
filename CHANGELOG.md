# Changelog

## Unreleased

Writing a file never replaces an existing one. `create`, `create_model`,
`evaluate`, `extract` and `write_copy`, in every language and in C, and
`gamut build`, refuse a destination that exists and leave it as it was;
1.3.0 and earlier replaced it. A script that writes the same name on each
run now stops at that refusal on its second run: choose a new name, or
remove the previous output yourself first. To add runs to an existing
file, open it with `gamut.open(path, mode="a")`. A `gamut build` that
failed part way used to delete the file it had replaced.

A refused replacement of an attribute keeps the attribute's previous
value. Before, the previous value was deleted first, so a refused
`set_attribute` on a name the file already had lost it.

## 1.3.0 (2026-10-25)

A file may carry a portion marking: a new optional root attribute,
`portion_marking`, holding free text the model's author set, which the
format does not interpret (specification sections 8 and 10.1). `evaluate`
copies it into every file evaluated from a model file that has one
(section 7.4), and `extract` and `write_copy` keep it. It is set with
`create` and `create_model` in Python (`portion_marking`), MATLAB
(`'portionMarking'`) and Julia (`portion_marking`), with `set_attribute`
in C and C++, and with the `portion_marking` key of a `gamut build`
document; `gamut info` shows it. Readers of earlier versions report it as
an attribute this version does not define (W5) and go on; they do not copy
it into an evaluation or a copy, and their writers refuse it.

## 1.2.0 (2026-10-23)

A file can no longer make a reader or a writer touch another path. A
dataset whose values HDF5 keeps outside the file, through external storage
or as a virtual dataset, passed validation and was read from that other
file (a constant as soon as the file opened), and appending wrote to it,
creating it if need be. Such a dataset is now an error (E22): the
validator reports it, opening refuses the file, and appending refuses it
before the file is opened to write. Appending also refuses a run-table
column that cannot grow (E20), before writing anything.

A read is refused (E23) before any buffer is sized when it would return
more than 2³⁰ values (8 GiB at 8 bytes a value); a file declaring billions
of rows made the Python, Julia and MATLAB layers allocate for them first.
The threaded reader no longer reads past its arrays when a field has fewer
axes than its selections.

The core reads compressed datasets itself, a chunk at a time, with one
path for one thread or many, and HDF5 is never handed a chunk it has not
checked. A chunk that is not stored whole, or that gzip does not inflate
to its full size, is refused (E23) on reading and before appending
rewrites it; HDF5 trusts these sizes, and a crafted chunk made it read past
its memory and return what lay there, or write past it when appending. A
filter other than gzip and shuffle is not read (E20). Reading a few
scattered rows or nodes is several times faster, up to twenty times on a
million-row table, and other reads and writes take the time they did.
Building the core needs HDF5 1.14 or later (every package carries 1.14.6).

MATLAB installs from a toolbox, `Gamut.mltbx`, attached to each release:
MATLAB R2023b or later on Linux, Windows or an Apple silicon Mac, and no
compiler. Each release also carries the core on its own for each platform
(`gamut-core-<version>-<platform>`, with its headers and CMake package) for
Julia, C and C++. Every package now includes the licences of HDF5 and zlib,
which the core links in.

Evaluating a damaged model file is refused in every language when the file
lacks what evaluation reads: a nearest model's numbers (`columns`, `lower`,
`upper`, `x`, `outputs`; E17), or a declaration such as a parameter's
bounds, a result's model or output, or a model's type or inputs. Python
and Julia raised a key error and MATLAB a field error instead. In Python
and Julia, `related` likewise refuses a quantile without its `q`.

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

The languages agree in more places. `gamut_create` from C, or
`gamut::create` from C++, with a mesh and no `per` is refused (E6), as
Python, MATLAB and Julia already refused it, where it took `fixed`. Cell
offsets of the wrong length are refused (E5) in Python, MATLAB and Julia
before the core reads them, as the C++ layer already did, and so are a
nearest model's inputs of unequal length. A parameter given only one of
`lower` and `upper` is refused (E16) in Python, MATLAB and Julia, where the
other was taken as 0 or the one given was dropped. An evaluation that
fails leaves no file behind, in every language. In Julia, a `true` note is stored as the integer 1,
and `related` keys a derivative along each coordinate axis separately, as
in Python.

A run table from a spreadsheet goes straight in: Python's `add_runs`
takes a pandas DataFrame and `add_run` one of its rows, and MATLAB's
`addRuns` takes a table, as `readtable` gives, with labels as text or
categorical.

The README and the guide start from the simplest study, a table of runs,
shown in Python, MATLAB, Julia and C++, and step up to a mesh from there;
the guide opens on the pattern every file follows and lists its pages by
what a study has. It shows how to publish a train and test split, says
that only `converged` marks a run as usable, that a new category name
extends a label's categories, and that unit names are checked only when a
read converts them. MATLAB can read a file with `ncread` and nothing
installed. Installing covers xarray, Xcode for MATLAB on macOS, and adds
the Julia package at the release tag that matches the wheel.

`help(gamut)` opens on the whole pattern, `help(gamut.create)` documents
every declaration, and `llms.txt` gives coding agents what Gamut is for,
the pattern, the mistakes that are easy to make, and every page.

A model in a file has its own step in the README and leads the models
page: a quadratic, of a model type defined in a few lines, is fitted in
Python to the README's sweep, saved, and evaluated in MATLAB by a MATLAB
class of the same type, with no Python involved; the built-in nearest
model is evaluated from Julia and C++. `help(gamut.create_model)` and
`llms.txt` show the whole model pattern and its easy mistakes, and
`help gamut.registerModelType` in MATLAB says what `call` receives and
returns. A model's `save` that returns an object which is not model data
is refused with the object named, where Python reported a
zero-dimensional array; so are a list mixing text with other values and
text with more than one axis, which Python flattened into strings (E18).
`gamut info` names the studies a model was trained on, and a model's
one-line description. `bench/scaling.py` times writes and reads as run
tables, one mesh and a mesh per run grow.

An answer from `evaluate` says, row by row, which inputs lie outside the
range the model was fitted on, and how far. The answer already kept the
model's bounds on its parameters; `outside(name)` measures each row's
value against them, in the parameter's units: 0 inside or on a bound,
negative below, positive above, NaN for a missing value. A parameter with
no bounds is refused rather than reported as inside. The core computes it
once (`gamut_outside` in C) for any data file, and it is `study.outside`
in Python, MATLAB and C++ and `Gamut.outside` in Julia. `evaluate` still
warns as well (W4). The models page and the MATLAB, Julia and C++ pages
show the call.

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

# Changelog

## Unreleased

- `gamut-format` stays at 2.0.0. Its 2.1.0, which only installed
  `bijective-gamut`, is yanked: both names install the same `gamut`
  module, so upgrading `gamut-format` to it removed that module. To move
  an environment, `pip uninstall gamut-format`, then
  `pip install bijective-gamut`; one broken by the upgrade is repaired by
  `pip install --force-reinstall --no-deps bijective-gamut`.

## 2.1.0 (2026-10-30)

**Upgrading from 2.0.** The file format (`gamut/1`) is unchanged, and the
C interface only adds calls, so programs written for 2.0 build and run
against 2.1; what `evaluate` now does differently is listed below. To
move from `gamut-format`, uninstall it, then install `bijective-gamut`
(see Unreleased).

- The Python package is now `bijective-gamut` on PyPI, and the Rust crates
  are `bijective-gamut` and `bijective-gamut-sys`; the code still says
  `import gamut` and `gamut::`. `gamut-format`, the name through 2.0.0,
  was published at 2.1.0 to install `bijective-gamut`; that release is
  yanked (see Unreleased).
- Rust: the `bijective-gamut` crate (`gamut` in code), over
  `bijective-gamut-sys`, the declarations of `gamut.h` that
  `rust/gamut-sys/generate.py` writes from it. It writes and reads
  data files with the calls of the other languages, evaluates model files
  whose models are the built-in nearest neighbour, and is held to the
  corpus. Every example has a Rust tab, and the reference a Rust page.
  The crates are added from this repository's release tag (not yet from
  crates.io).
- `related` in every language, read in the core: what describes a result
  (its standard deviation, quantiles and derivatives, and the parts of its
  vector) comes from `gamut_related` in the C interface. MATLAB
  (`study.related(name)`) and C++ (`study.related(name)`, a
  `gamut::Related`) gain it, and Python's and Julia's now read it from the
  core, so the four agree.
- `evaluate` is one implementation, in the core: the `gamut_evaluation_*`
  calls check the inputs (E2, E5, E9, and the W4 finding, with one
  message in every language), run the built-in models and write the data
  file. Python, MATLAB and Julia only call the registered model types, and
  a C program can evaluate a model file itself. `gamut_evaluate_begin`
  stays for 2.0 callers. Along the way:
  - coordinates given to `evaluate` are the data file's, per run, as
    section 7.4 says; they were dropped for a model file whose mesh is
    fixed;
  - an int64 input past 2^53 is compared with its bounds exactly and
    evaluated, where it was refused (E4);
  - W4 says in how many rows an input lies outside, the same in every
    language;
  - a model file whose results read one model output at two widths (a
    scalar and a field) is refused (E17) before any model runs;
  - in Python, a complex, boolean or text input or coordinate is refused
    (E4), where it was cast.

## 2.0.0 (2026-10-29)

**Upgrading from 1.3.** The file format is unchanged (`gamut/1`), so
files move between 1.3 and 2.0, short of the new limits below. Code
written for 1.3 can stop at, or behave differently after, these changes;
the fixes further down also correct results that were wrong, such as a
`select` on int64 values past 2⁵³.

- Creating a file never replaces an existing one: `create`,
  `create_model`, `extract`, `write_copy`, `evaluate` with a path,
  `gamut build`, `gamut-vtk import`, and `gamut get` without `--force`.
- A parameter is float64 unless declared int64; integers given to it no
  longer make it int64.
- In MATLAB, `[]` as rows, nodes or cells selects none; `':'`, or leaving
  them out, selects every one.
- Input that was stored wrongly is refused: a field given sites × runs (a
  square array cannot be told apart, and is taken as runs × sites), a
  label given `None` or NaN, a fractional, out-of-range, text or boolean
  value for an int64 model input, an integer that float64 would round, a
  group member given two different geometries in one batch, and a
  negative `--rows` position on the command line.
- A file whose category tables together, or a model whose arrays
  together, pass the cap one table or array had is refused (E26) when it
  is opened or read; 1.3 allocated for them without limit.
- In C, every array argument comes with its length, and every array the
  core fills with its capacity: `gamut_batch_values` takes `first_axis`;
  `gamut_geometry_points`, `gamut_geometry_cells`, `gamut_tree_set_array`
  and `gamut_nearest_call` take counts; `gamut_shape` and
  `gamut_tree_array_info` take `rank, shape, capacity`.
  `gamut_units_parse` is `gamut_units_valid`.
- On the command line, every failure under `--json` is
  `{"problems": [{"rule", "path", "message"}]}`; it was `{"error": {...}}`
  or `{"problems": [{"key", "message"}]}` by command, and argparse's own
  mistakes printed text (`validate` still prints its findings). Success
  documents no longer carry an empty `problems`. A misused `gamut get`
  exits 2 before creating its output.
- In Python, `related(name)["vector"]` lists the vector's parts only, as
  Julia did; a statistic or derivative of a part that carries the same
  `vector` was listed among them.
- Python 3.11 or later is required (3.10 reaches its end of life this
  month), NumPy 1.26 or later (it was 1.24, never tested) and Julia 1.10
  or later (it was 1.9, never tested). MATLAB R2023b or later is
  unchanged. Each minimum is now tested, with Python 3.14 too, and **none
  of them rises within 2.x**.
- In C++, `get_parameter<T>` and `get_constant<T>` name the type: `double`,
  or `int64_t` for a value declared int64. Another type is refused rather
  than rounded or truncated.
- Two rules each split in two: appending to a file whose growable
  dimensions are fixed is E25 (it was E20, which keeps storage the format
  forbids), and a limit reached is E26 (it was E23, which keeps storage a
  reader cannot read). Code that tests for E20 or E23 checks the new
  codes too.

The rest of this section says what changed and why.

Creating a Gamut file never replaces an existing one. `create`,
`create_model`, `evaluate`, `extract` and `write_copy`, in every language
and in C, `gamut build` and `gamut-vtk import` refuse a destination that
exists and leave it as it was; 1.3.0 and earlier replaced it. A script that
writes the same name on each run now stops at that refusal on its second
run: choose a new name, or remove the previous output yourself first. To
add runs to an existing file in Python, open it with
`gamut.open(path, mode="a")`. A `gamut build` that failed part way used to
delete the file it had replaced.

A parameter is float64 unless declared int64 (`"dtype": "int64"`; in C++,
`declare_parameter<int64_t>`). 1.3.0 and earlier stored an undeclared
parameter as int64 when its first values were integers, so a Python sweep
begun with `range(0, 11, 2)` refused 2.5 when appended to, and the same
program wrote int64 from Python and float64 from MATLAB. Files are
unchanged: an int64 parameter stays valid and reads as before. Code that
gives integers to an undeclared parameter now writes float64; declare
int64 where whole numbers are meant.

A refused replacement of an attribute (a value of about 64 KiB or more)
keeps the attribute's previous value. Before, the previous value was
deleted first, so the refusal lost it.

A field given the wrong way round, sites × runs instead of runs × sites,
is refused. It was stored scrambled, each run holding a mix of every run's
values. The C interface's `gamut_batch_values` takes a new `first_axis`
argument, the length of the caller's first axis or 0 for a flat array,
and the core refuses a first axis that is not the batch's runs. A square
array cannot be told apart and is taken as runs × sites.

A label given as `None` or NaN in Python is refused (E5); it used to
become a category named "None" or "nan". A category name that is not valid
UTF-8 is refused when the file opens (E4), in every language, where Python
raised `UnicodeDecodeError`. A position above 2⁶³ − 1 is reported as given
rather than wrapped to a negative number. `get_points` on a file with no
mesh says so, in every language, instead of asking for a row.

A group member given two different geometries in one batch is refused by
the core, in every language. MATLAB kept the first geometry silently.

`open` with a refused `threads` value closes the file it opened, in Python
and MATLAB; the file stayed open, and a later append to it failed. MATLAB's
`'compression', false` works; it always failed with an unknown command.

Appending two files in which one name is a parameter in one and a label
in the other is refused; it crashed the process. A `where` text with
parentheses nested deeper than 64 levels is refused; deep enough nesting
overflowed the stack and crashed. Appending to a file whose label codes
are int64, as §10.1 allows another writer to store them, works; it failed
with an internal error and left the file's columns of different lengths.

Values read from the file that locate others (a changing mesh's run
starts and instance numbers, cell offsets) are range-checked before any
arithmetic on them, so a damaged file is refused or reported (E21, E10)
instead of overflowing into wrong answers. `select` compares an int64
parameter or scalar exactly with an integer literal, one outside int64's
range included; as doubles, values above 2⁵³ that differ compared equal.
Appending a changing mesh's geometry to int64 mesh labels takes codes
beyond int32. BitRound no longer rounds a value near the largest finite float up
to infinity. Names are checked against ASCII letters and digits whatever
locale the host program has set.

E20 and E23 each meant two things a caller handles differently. E20 is
now storage the format forbids, and appending to a valid file whose
growable dimensions are fixed is E25: the file is read-only, and
`write_copy` makes one that grows. E23 is now an object a reader cannot
read (a chunk index it cannot use, a chunk of the wrong size, a filter
that fails), and E26 is a count past one of the caps in
`docs/security.md`. SPEC.md, the corpus and every language follow.

The C interface states the length of every array it reads and the
capacity of every array it fills, so the core checks what a binding passes
instead of trusting it: the points' count, the offsets' count (one more
than the cells), a model array's count against its shape, and each
nearest-model column's length. `gamut_shape` and `gamut_tree_array_info`
take the rank, the shape and the shape's capacity, in that order, and
refuse a capacity below the rank. `gamut_units_parse` is renamed
`gamut_units_valid`, which says what its 1 means; it is the one function
that does not return 0 on success.

A group reachable by more than one hard link is walked once; a chain of
such groups made validation, append, extract and `write_copy` take time
that doubled with every level. `/private` may hold them, as §8 lets it
hold any structure; model data, a tree, refuses them (E18). The category
tables read when a file opens share one budget, the cap one table had, and
so does validation; a model's arrays read together share one budget, the
cap one array had (E26). Many tables, or many arrays, each under its own
cap could make opening a file, or reading or validating a model,
allocate gigabytes.

The command line reports malformed input as `error: …` with the exit
status the guide gives instead of a Python traceback: a build or append
document that is not JSON exits 1, and `--zone` without `=`, a zone name
not in the label's table, or a `--rows` position outside the file exits 2.
`--rows` positions are checked by the core for every output type; for a
`.gamut` output, `-1` meant the last row.

The validator checks what SPEC.md says and it did not: a model-data
array without its dimension scale (E19); an integer that is not int64 or
a number that is not float64 in model data (E18, which reading model data
now refuses too); a string attribute stored wider than its UTF-8 bytes
(E3); a derivative with respect to `coordinates` along an axis the
coordinates do not have (E13); and the vector and axis of a result whose
statistic this version does not define. A required object or attribute
that is absent is E2, whatever rule its contents would break: a label's
`category`, the mesh's `kind` and `support_id`, a changing mesh's
`instance_nodes`, the cell arrays. A table's repeated entry is reported
once.

SPEC.md settles where an independent reader could diverge. A units string
holding a space outside ASCII, such as a no-break space pasted from a web
page, does not parse (E7). Names use ASCII letters and digits. A scale's
encoding is what a writer produces, not a rule. A root dataset without a
`role` is ignored (W5). A file whose growable dimensions are fixed, as
some netCDF writers leave them, is valid and read-only: appending says so
and points to `write_copy`, which makes a copy that grows.

The corpus requires each rule case to break exactly its rules, in Python,
Julia and MATLAB; it accepted any extra finding. Its rule cases no longer
break rules by accident, every valid data file is appended to itself, and
it gains a valid file of int64 columns and hostile files of several large
tables and a deeply nested `where`.

MATLAB takes `"double-quoted"` strings wherever it takes text, notes and
model numbers included, refuses sparse arrays, and takes cell arrays given
as any integer class, read by their class; integer arrays
that were not double were read as int64, past the end of their buffer.
An open study keeps the MATLAB gateway loaded, so `clear mex` no longer
orphans it, and MATLAB finishes open files when it exits. A refused call
frees what it built before MATLAB reports the error. In Julia, the
library's symbols are looked up under a lock from any thread, and a study
left to the garbage collector removes its temporary file as `close` does.

The guide and SPEC.md say what an append costs when it is interrupted: a
batch refused for its own data leaves the file as it was, every such
check being made before the first write, but a write that fails or a
process killed while it appends can leave the whole file unreadable. Keep a copy of a file you cannot regenerate, or append each
job's own file at the end.

In MATLAB, `[]` as rows, nodes or cells selects none and `':'` (or leaving
them out) every one; `[]` meant every row, so the rows of a `select` that
matched nothing read the whole file. MATLAB passes integer arrays to the
core in their own class, so int64 codes above 2⁵³ are not rounded through
double. An int64 model input given fractional or out-of-range values is
refused in Python and MATLAB, as in Julia, instead of being truncated; an
unsigned array above int64's range is refused instead of wrapping. Julia's
`open` closes the file when its `threads` value is refused. An integer
written to a float64 parameter, scalar, field or coordinate, or given to a
float64 model input, that a float64 cannot hold exactly (past 2⁵³) is
refused (E4) in every language; it was rounded silently. Opening a file that does not exist says so, rather than
that it is not HDF5. A column with the wrong number of values names it and
both counts. A Python `Study` prints its path, kind, type and row count.

A group member repeated with the same values in another shape (4 × 2 and
2 × 4 points) is refused as a different geometry. Replacing an attribute
works however many one-character names the object already holds. The
validator checks a model-data scale's extent and attribute creation order
as it checks every scale. A `where` nested past the cap is E26, as the
limits in `docs/security.md` are. `gamut get` refuses to write over an
existing `.csv`, `.npy` or `.npz` output unless given `--force`, and
checks `--rows` without reading the rows.

A file whose `DIMENSION_LIST` attribute is not HDF5's list of dimension
scales (an integer, a string) is reported (E19) instead of crashing
`validate` and `open`: HDF5's scale calls follow the attribute as
references, and Gamut now checks its type before they read it.

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

The format ([SPEC.md](https://bijective-systems-org.github.io/gamut/reference/specification.html)) is redesigned around the study: a run
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
HDF5 plugins ([security](https://bijective-systems-org.github.io/gamut/security.html)). The guide has fourteen pages,
each held to a runnable example by the tests, and the
[benchmarks](https://bijective-systems-org.github.io/gamut/benchmarks.html) cover two studies.

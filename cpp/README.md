mestra in C++
=============

Install
-------

CMake, a C++17 compiler, and HDF5 with its headers and the high-level
`H5DS` dimension-scale API. `HDF5_ROOT` is the installation prefix
containing the headers (including `H5DSpublic.h`) and C/high-level
libraries; library names and locations depend on the platform. Tests
have the additional Python requirements below.

    cmake -S cpp -B cpp/build -DHDF5_ROOT="$HDF5_ROOT"
    cmake --build cpp/build --parallel 2

That gives `libmestra`, `mestra-cli` and the seven examples in
`cpp/build`; `mestra-cli` with no argument says what it does. The tests
need a Python 3 with `h5py` too, and three corpus files too big to commit:

    python vectors/generate.py --on-demand     # once
    cmake -S cpp -B cpp/build -DHDF5_ROOT="$HDF5_ROOT" \
          -DPython3_EXECUTABLE="$(which python3)"
    ctest --test-dir cpp/build --output-on-failure

Run these configure/build/test commands from the repository root. Without
a discovered Python interpreter, CMake registers only the unit test and
warns that corpus/metadata/hostile/example lanes are absent. Check the
registered lanes before treating a CTest result as conformance evidence.
Multi-configuration generators add a configuration directory to example
paths; select that configuration when building and testing.

`-DMESTRA_SANITIZE=ON` builds the suite under the address and
undefined-behaviour sanitizers.


The ten-line example
--------------------

    #include "mestra/mestra.hpp"

    mestra::Dataset ds;
    ds.writer = "my tool 1";
    ds.created = "2026-09-20T00:00:00Z";
    ds.add_key("mach", {0.4, 0.8}, "condition", "1");
    mestra::Support& s = ds.add_axis_support("s0", {0., 1., 2.}, "m");
    mestra::add_node_array(s, "pressure",
                           {101., 102., 103., 201., 202., 203.}, "Pa",
                           {"row", "node"});
    mestra::write(ds, "run.mes");

    const mestra::Dataset d = mestra::read("run.mes");
    const mestra::Array& p = d.support("s0")->node_array("pressure")->data;
    p.at_f64({1, 2, 0});                                  // 203.0

The same data and the same value in all four languages.
`../docs/examples/` has seven worked examples, one per concept, each
with a `cpp.cpp` beside its `python.py`; `../docs/guide.md` says what
the concepts mean.


Growing a file row by row
-------------------------

A producer that computes one row at a time keeps one file:

    mestra::Dataset row = one_more_row();       // built like a whole file
    mestra::append_rows(row, "run.mes");        // the file, one row longer

`append_rows(rows, path)` grows the file at `path` by the rows of a
dataset of the same structure: the same keys, scalars, supports and
arrays with the same attributes, and the same values in every array
that does not vary by row. Category ids are matched by their entry's
name, so a status table built from the new rows alone maps onto the
file's; key bounds widen to cover the new values; notes on the appended
dataset replace the file's; `created`, `writer` and `/private` stay.
The result is what one write of every row would have produced, in
content though not in bytes: the chunk shapes are the ones the file was
created with, and `validate` says so (W12) once they are no longer the
default for the row count. The file is grown beside itself and moved
into place only after it validates, so a failure leaves it as it was,
and any structural difference is refused with the difference named. With
`AppendOptions::replace_by` naming the id key, a row that shares an
existing row's id is written over it instead of after the last row.


Axis order and permute by name
------------------------------

Arrays come back in C order, the stored order of SPEC.md section 4:
`(row | instance, [draw], node | cell, component)`. `Array::dims` names
every axis and `Array::axis(name)` gives its position, so a value is
taken by name and never by counting axes. The `dims` a builder is given
names the axes of the array *you* flattened, in your own order, and the
builder permutes into stored order. The names are what two languages
agree on: a column-major reader hands the same array back with its axes
reversed and answers the same question with the same number. Above,
`pressure` is `("row", "node", "component")` and its value at row 1,
node 2, component 0 is 203.0.


What the reader refuses
-----------------------

A strict `read`, which is the default, refuses E01, E16, E19, E25, E26,
E29, E30, E40 and E41, and any fault no rule covers, throwing
`mestra::Error` with the first identifier and every finding; a semantic
fault never stops a read. `mestra::read(path, {/*strict=*/false})` reads
what it can and lists what it refused in `Dataset::not_read`. Findings
are a `mestra::Report`, one per rule per object, and the limits and
depth caps a hostile file meets are in `include/mestra/io.hpp`. Native
HDF5 can still crash or hang on damaged bytes; untrusted reads need a
separate killable process and external deadline. See
[damaged-file limits](../docs/compatibility.md#damaged-files).


Post-processing this package does not carry
-------------------------------------------

`time_series` and `grouped_split`, two of the four helpers of
`../docs/api-conventions.md` section 4, are not here. Both are analysis
over rows rather than anything the format decides: a time series is a
selection and a sort a caller writes in three lines over the arrays
this library already hands them, and a split is an assignment of units
of generalisation to parts, which SPEC.md section 31 pins down to the
draw, so one seed names one split in every language. Python and Julia
carry both. `compute_weights`, `integrate` and `field_statistics` are
here for the opposite reason: a weight array is computed from
connectivity and never imported, which is a rule and not a convenience.
So is `prediction`: one record for a stored slot and for a served one
is the contract of SPEC.md section 10, not analysis.


Where to go next
----------------

`../docs/guide.md` for the format in plain words, one example per
concept. `../SPEC.md` by section for the normative text, which this
code is not. `../docs/api-conventions.md` for anyone comparing two
languages, and `include/mestra/` for this API call by call.

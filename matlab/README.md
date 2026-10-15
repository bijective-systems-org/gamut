The MATLAB interface
====================

A reader, a writer, a validator and the reference callable for the
open dataset format, in base MATLAB: HDF5 through the low-level
interface, the keys table a plain `table`, the tests
`matlab.unittest`. Everything is under the package `mestra`, and
every public call carries its own help text: `help mestra.read`.


Install
-------

    addpath('<this repository>/matlab')

That is the whole installation: base MATLAB, no toolbox. Three corpus
files are too large to commit and are made once, before the first run:

    python vectors/generate.py --on-demand

Checked writes require MATLAB's JVM and a filesystem supporting Java's
atomic move, so a failed replacement cannot delete the old file.
Non-ASCII fixed strings are explicitly refused by this implementation.
See [implementation capabilities](../docs/compatibility.md).

Then the suite, corpus and all:

    matlab -nodisplay -batch \
        "addpath('<repo>/matlab'); run('<repo>/matlab/tests/run_tests.m')" \
        < /dev/null


The ten-line example
--------------------

    d = mestra.Dataset();
    d.writer = 'my tool 1';
    d.addKey('mach', [0.4 0.8], 'condition', '1');
    d.addAxisSupport('s0', [0 1 2], 'm', 'Dims', {'component', 'node'});
    d.addNodeArray('s0', 'pressure', [101 102 103; 201 202 203], ...
                   'field', 'Pa', 'Dims', {'row', 'node'});
    mestra.write(d, 'run.mes');

    r = mestra.read('run.mes');
    a = r.nodeArray('s0', 'pressure');
    p = mestra.permute(a.values, a.dims, {'row', 'node', 'component'});
    p(2, 3, 1)                              % 203

The same dataset and the same value in all four languages.
`../docs/examples/` holds seven worked examples, one per concept, each
with a `matlab.m` this suite runs; `../docs/guide.md` says what they mean.


Axis order, and permute by name
-------------------------------

HDF5 stores an array in C order and MATLAB is column major, so
**every array this package hands you has its axes reversed with
respect to the file**. The file's logical order is

    (row | group | nothing, [draw], node | cell, component)

so `a` above comes back as `(component, node, row)`, and `a.dims`
names its axes in that same order. The names are what two languages
agree on: a value is found by name and never by counting axes, and

    mestra.permute(a.values, a.dims, wanted)

is the whole idiom. A name in `wanted` the array does not have becomes
an axis of length one; a name it has that `wanted` leaves out is
dropped only when its length is one. Row 1, node 2, component 0 of the
example above is 203, here and in every other language.


What the reader refuses
-----------------------

`mestra.read` refuses rather than half reads a file that breaks one of
the nine structural rules -- E01, E16, E19, E25, E26, E29, E30, E40,
E41 -- which `help mestra.read` names one by one.
`mestra.read(path, 'Strict', false)` returns what could be read and
lists the rest in `d.skipped`, one line each. Everything else a file
gets wrong is a finding and not a refusal: `mestra.validate` always
returns them and `mestra.report` prints them.

`mestra.read` materialises the file; use `mestra.open` for metadata and
subsequent row-range access. Metadata opens may read category tables and
`/row_support`, while slot values and callable-dictionary datasets are
deferred (API conventions section 7). Native HDF5 can still crash or hang;
untrusted reads need a separate killable process and external deadline.
See [damaged-file limits](../docs/compatibility.md#damaged-files).


Where to go next
----------------

`../docs/guide.md` is the format in plain words, one worked example
per concept; `../SPEC.md` is the reference the guide links into by
section; `../docs/api-conventions.md` compares the four languages.

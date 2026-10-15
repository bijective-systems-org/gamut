A callable and evaluation
=========================

Any slot may hold stored data or name a callable that produces it, so
this example represents a fitted model with no rows and declared key
bounds. A model file may also retain rows or mix stored and callable
slots; bounds do not certify predictive accuracy throughout a domain.
Evaluating that file on a keys table gives a
file with the same slots, now holding data. `affine` is the one
callable type the format defines, for testing without any proprietary
model.

The data
--------

The mesh of `../a-support-and-a-field`, with coordinates that do not
vary, and no rows at all.

    mach      key, role condition, units "1", bounds 0.1 to 0.9
    alpha     key, role condition, units "degree", bounds 0.0 to 8.0
    m1        an affine callable over the keys ["mach", "alpha"],
              y = A x + b per output:
              cl        A = [[2.0, 0.1]]   b = [0.05]  shape = []
              pressure  A = [[1.0, 0.0],   b = [0.0,   shape = [6, 1]
                              [2.0, 0.0],        0.1,
                              [3.0, 0.5],        0.2,
                              [4.0, 0.5],        0.3,
                              [5.0, 1.0],        0.4,
                              [6.0, 1.0]]        0.5]
    pressure  node array slot, units "Pa", source callable:m1
    cl        scalar slot, units "1", source callable:m1

The keys table it is evaluated on is one row, mach 0.5 and alpha 4.0.
The same numbers are worked through in SPEC.md section 27.

Run it
------

    python python.py
    matlab -nodisplay -batch "addpath('<repo>/matlab'); run('matlab.m')"
    ../../../cpp/build/examples/callables-and-evaluation
    julia --project=../../../julia julia.jl

It writes `model.mes` in the working directory, reads it back and
evaluates it. The evaluated dataset holds data and no callables.

Run the examples from this directory. First configure and build the C++
programs from the repository root with `cmake -S cpp -B cpp/build` and
`cmake --build cpp/build --parallel 2`, using the HDF5 setup in
[the C++ README](../../../cpp/README.md). The executable paths above
assume a single-configuration generator; otherwise use its configuration
subdirectory.

Expected output
---------------

    rows: 0 callables: ['m1']
    cl source: callable:m1
    evaluated rows: 1 source: data
    cl: 1.45
    pressure: [0.5 1.1 3.7 4.3 6.9 7.5]

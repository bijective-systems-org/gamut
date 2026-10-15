Rows and roles
==============

A row is one observation: one member of a family at one operating
point. Every key is a per-row column that says where the row sits in
that space, and its role says what kind of column it is; a scalar is a
per-row quantity with units. A file of keys and scalars, with no
support and no field, is already a complete file.

The data
--------

Six rows: three members of one family at two Mach numbers each.

    mach    key, role condition, units "1"
            0.4, 0.8, 0.4, 0.8, 0.4, 0.8
    member  key, role group, categories ["wing_a", "wing_b", "wing_c"]
            0, 0, 1, 1, 2, 2
            declared the unit of generalisation
    cl      scalar, units "1"
            0.21, 0.25, 0.30, 0.36, 0.41, 0.48

The bounds on `mach` are not given, so the writer records the observed
range, 0.4 to 0.8.

Run it
------

    python python.py
    matlab -nodisplay -batch "addpath('<repo>/matlab'); run('matlab.m')"
    ../../../cpp/build/examples/rows-and-roles
    julia --project=../../../julia julia.jl

It writes `family.mes` in the working directory and reads it back.

Run the examples from this directory. First configure and build the C++
programs from the repository root with `cmake -S cpp -B cpp/build` and
`cmake --build cpp/build --parallel 2`, using the HDF5 setup in
[the C++ README](../../../cpp/README.md). The executable paths above
assume a single-configuration generator; otherwise use its configuration
subdirectory.

Expected output
---------------

    6 rows, 2 keys
    mach condition 1
    member group member
    generalisation unit: member
    cl at row 3: 0.36
    cl units: 1

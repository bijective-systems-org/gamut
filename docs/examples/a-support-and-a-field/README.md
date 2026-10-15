A support and a field
=====================

A support is the structure a field lives on: here a mesh of six nodes
and two quadrilaterals. A field is an array on that support which
declares what it varies along, so `pressure` varies along the row and
the coordinates vary along the member. Every array knows the name of
each of its axes, so a value is found by name and never by counting
axes.

The data
--------

The six rows of `../rows-and-roles`, without `cl`, on one mesh.

    nodes       (0,0) (1,0) (2,0) (0,1) (1,1) (2,1), with the x of
                every node multiplied by 1.0 for wing_a, 1.5 for
                wing_b and 2.0 for wing_c
    cells       cell_types [9, 9] (two VTK quadrilaterals)
                cell_offsets [0, 4, 8]
                cell_connectivity [0, 1, 4, 3, 1, 2, 5, 4]
    coordinates varies group:member, units "m", shape (3, 6, 2)
    pressure    varies row, units "Pa", node array, shape (6, 6)
                row r, node n holds 100*(r+1) + (n+1): row 0 is
                101 to 106, row 5 is 601 to 606

One support makes the file structurally aligned. This example constructs
known corresponding nodes; the declaration alone would not establish
physical correspondence between independent producers.

Run it
------

    python python.py
    matlab -nodisplay -batch "addpath('<repo>/matlab'); run('matlab.m')"
    ../../../cpp/build/examples/a-support-and-a-field
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

    aligned: True nodes: 6 cells: 2
    pressure ('row', 'node', 'component') Pa
    pressure at row 1 node 3: 204.0
    x of node 2 for wing_b: 3.0

`instance` is the alias for the leading axis of an array that varies
along a group, so `at(instance=1, node=2, component=0)` is wing_b's
node 2. A column-major reader hands the same array back with its axes
in the opposite order and answers 3.0 to the same question.

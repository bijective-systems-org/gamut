Uncertainty as draws
====================

A model's output is stored with the same roles as data, plus a
`statistic` saying what the numbers are. A draw is a whole field at
once, joint across the nodes, so the draws of a field carry an extra
`draw` axis; mean and standard deviation are separate slots that name
the quantity they summarise with `of`. Anyone can recompute the
summaries from the draws in the file.

The data
--------

Two rows on the mesh of `../a-support-and-a-field`, coordinates not
varying, four draws per row.

    mach           key, role condition, units "1"
                   0.4, 0.8
    base           row 0: 101, 102, 103, 104, 105, 106
                   row 1: 201, 202, 203, 204, 205, 206
    pressure       node array, units "Pa", statistic draw,
                   axes (row, draw, node); draw d of row r is base
                   plus [-1, -1, 1, 1][d] at every node
    pressure_mean  node array, units "Pa", statistic mean,
                   of "pressure": the mean over the draw axis
    pressure_std   node array, units "Pa", statistic std,
                   of "pressure": the standard deviation over it

The four offsets are chosen so the mean is `base` exactly and the
standard deviation is exactly 1.

Run it
------

    python python.py
    matlab -nodisplay -batch "addpath('<repo>/matlab'); run('matlab.m')"
    ../../../cpp/build/examples/uncertainty-as-draws
    julia --project=../../../julia julia.jl

It writes `draws.mes` in the working directory and reads it back.

Run the examples from this directory. First configure and build the C++
programs from the repository root with `cmake -S cpp -B cpp/build` and
`cmake --build cpp/build --parallel 2`, using the HDF5 setup in
[the C++ README](../../../cpp/README.md). The executable paths above
assume a single-configuration generator; otherwise use its configuration
subdirectory.

Expected output
---------------

    pressure ('row', 'draw', 'node', 'component') draw
    draw 0 of row 0: [100. 101. 102. 103. 104. 105.]
    pressure_mean mean of pressure at row 0, node 0: 101.0
    pressure_std std of pressure at row 0, node 0: 1.0

How many draws there were, from which seed, in what batches, is the
producer's business and not the file's.

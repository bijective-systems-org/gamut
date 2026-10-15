Groups and splits
=================

A group key says which rows belong together, and one group is declared
the unit of generalisation: here the two rows of a member are one
unit. A split that puts rows of one unit on both sides is not a
generalisation test, and the file says so. `grouped_split` moves whole
units, so a member is never in both parts.

The data
--------

The six rows of `../rows-and-roles`, plus a split key written the
naive way, by row.

    mach    key, role condition, units "1"
            0.4, 0.8, 0.4, 0.8, 0.4, 0.8
    member  key, role group, categories ["wing_a", "wing_b", "wing_c"]
            0, 0, 1, 1, 2, 2
            declared the unit of generalisation
    cl      scalar, units "1"
            0.21, 0.25, 0.30, 0.36, 0.41, 0.48
    split   key, role split, categories ["train", "test"]
            0, 0, 0, 1, 1, 1

The first three rows are wing_a twice and wing_b once, so that split
cuts wing_b in half. `grouped_split` is asked for 0.67 train and 0.33
test with seed 0, and returns whole members. Which member lands where
is SPEC section 31's algorithm and not the language's own generator,
so Python, MATLAB and Julia print these rows. The C++ example stops
after the first two leak-report lines: it does not ship `grouped_split`
or perform the seeded selection shown below.

Run it
------

    python python.py
    matlab -nodisplay -batch "addpath('<repo>/matlab'); run('matlab.m')"
    ../../../cpp/build/examples/groups-and-splits
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

    unit of generalisation: member
    the split in the file leaks: ['wing_b']
    train rows [0, 1, 2, 3] members ['wing_a', 'wing_b']
    test rows [4, 5] members ['wing_c']

The split stored in the file is left alone: reporting it is the
format's job, and fixing it is the producer's. `../validating` shows
the same leak as the warning W01.

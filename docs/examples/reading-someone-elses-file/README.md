Reading someone else's file
===========================

A file states its own structure, so a reader can ask what is in it
before it knows anything: how many rows, whether it is aligned, which
keys with which roles, which supports, which slots on them. A value is
then taken by name, both the slot's name and the name of each axis. A
row range can be read without touching the rest of the file.

The data
--------

`../mesh_two_rows.mes`, which is listed object by object in
`../../example.md` and was written with h5py alone, by no
implementation.

    mach      key, role condition, units "1", bounds 0.1 to 0.9
              0.40, 0.80
    member    key, role group, categories ["wing_a", "wing_b"]
              0, 1
    cl        scalar, units "1"
              0.25, 0.55
    s0        mesh support, 6 nodes, 2 quadrilaterals
    pressure  node array, units "Pa", varies row
              row 0: 101 to 106, row 1: 201 to 206
    region    cell array, role label, categories ["inlet", "outlet"]
              0, 1

It is the two-member half of the family the other examples build.

Run it
------

    python python.py
    matlab -nodisplay -batch "addpath('<repo>/matlab'); run('matlab.m')"
    ../../../cpp/build/examples/reading-someone-elses-file
    julia --project=../../../julia julia.jl

It reads the committed file and writes nothing.

Run the examples from this directory. First configure and build the C++
programs from the repository root with `cmake -S cpp -B cpp/build` and
`cmake --build cpp/build --parallel 2`, using the HDF5 setup in
[the C++ README](../../../cpp/README.md). The executable paths above
assume a single-configuration generator; otherwise use its configuration
subdirectory.

Expected output
---------------

    valid: True
    2 rows, aligned: True
    keys: [('mach', 'condition'), ('member', 'group')]
    scalars: ['cl']
    support s0 mesh 6 nodes 2 cells
      node arrays: ['pressure']
      cell arrays: ['region']
    pressure ('row', 'node', 'component') Pa row
    pressure at row 1 node 3: 204.0
    row 0 alone: (1, 6, 1)
    region is a label over ['inlet', 'outlet']

`mestra info ../mesh_two_rows.mes` prints the same survey from the
command line.

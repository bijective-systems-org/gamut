# The file underneath

A Gamut file is HDF5, laid out so that it is also a valid netCDF-4 file:
named dimensions, attributes that are strings or numbers, groups for
structure, and nothing a netCDF tool cannot read. h5py, netCDF4, xarray,
the netCDF command-line tools and MATLAB's `ncread` all read it without
this package; ParaView shows a study through the VTK files `gamut-vtk`
writes ([VTK](../guide/10-vtk.md)). The root attribute
`format`, `gamut/1`, says what it is; the `.gamut` extension is only a
convention.

## The layout

The run table is at the root: one dataset per parameter, label and
scalar, each over the `row` dimension, with its role and, but for a
label, its units as attributes. A label stores its codes there and its
names under `categories`; a constant is a dataset of one value. A mesh is the group `mesh`, holding the coordinates, the
cells in VTK's arrays (types, offsets, connectivity), the mesh labels,
and the fields. The main arrays of the cylinder of
[example 2](../guide/02-one-mesh.md), as h5py lists them:

```text
gamma                       float64 (9,)
row                         int64 (9,)
mesh/coordinates            float64 (576, 2)
mesh/cell_types             uint8 (528,)
mesh/cell_offsets           int64 (529,)
mesh/cell_connectivity      int64 (2112,)
mesh/node_labels/surface    int32 (576,)
mesh/node_fields/cp         float64 (9, 576)
```

The field `cp` is one array of 9 runs × 576 nodes. Its rows are the runs
in the order of `row`, which holds each run's id, so a generic tool that
shows the row index shows the id. A model file adds `models`, one group
per model holding its numbers.

## Storage

Every array that grows with the runs is chunked along that dimension, so
runs can be appended in place, a batch at a time, without rewriting what
is there. Chunked arrays are compressed with gzip and shuffle, level 1 by
default, filters every HDF5 build has, MATLAB's and Julia's included. A file keeps track of
the space a rewritten chunk leaves free, so a file appended one run at a
time stays the size of its data: 3,000 single-row appends of 20 columns,
the file reopened for each, give 0.49 MB, against 32 MB without.

Results and coordinates are stored at the precision they were given,
float32 or float64, and converted only when asked; parameters are float64,
or int64 for counts. A writer may round a result's mantissa to
fewer bits, recording how many it kept as netCDF-C does for the same
algorithm; it is off by default.

## When a write fails

Every check of a batch's own data is made before its first write, so a
batch refused for its data leaves the file as it was. HDF5 does not keep
a file consistent on disk while it is written, though: a failure of the
file itself during a write (a full disk, a damaged chunk), or a writer
stopped partway, can leave it unreadable, rows written before included.
Keep a copy of a file that matters before appending to it.

## Reading files from elsewhere

Readers check every size before they allocate memory, cap what one read
may decode, and never follow a link out of the file. What they check, and
what they cannot, is in [files from outside](../security.md).

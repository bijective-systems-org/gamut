Two files, listed in full
=========================

This is the document to keep open while implementing. It lists two
valid files object by object and value by value: a small file with
rows and stored data, and a file with no rows whose two slots are
served by one `affine` callable. Both are in docs/examples/ and both
were written by docs/examples/make_examples.py, which is the rules of
SPEC.md sections 18 to 25 read literally and nothing else.

Both files have been opened by two netCDF-4 readers that share no
code, netCDF-C and a pure-Python one, and by xarray through each of
them; every dimension name below came back intact from both. Nothing
here is a claim about what should work.

The listings are what `h5dump -n` and `h5dump -A` show, condensed: the
object list verbatim, then each object with its dtype, shape, chunk
shape, the dimension scale on each axis, and its attributes with their
values and their types. `(scale)` marks a dimension scale dataset;
none of them holds a value that anyone reads. "u8" means an eight-byte
unsigned integer and "i4" a four-byte signed one; every numeric
value dataset is little-endian and in C order; the dimension-scale
placeholders explicitly listed as >f4 are big-endian float32 (SPEC21).
Every string defined by this layout is fixed-length
UTF-8 with NUL padding.


File one: mesh_two_rows.mes
===========================

Two rows of one parametric family. One mesh support of six nodes and
two quadrilaterals. One field, one label, one scalar, one group key
with a category table, and bounds on the condition key. Every row is
on the same support, so the file is aligned and has no /row_support.

Object list
-----------

    HDF5 "mesh_two_rows.mes" {
    FILE_CONTENTS {
     group      /
     group      /categories
     dataset    /categories/member
     dataset    /categories/region
     dataset    /category_member
     dataset    /category_region
     dataset    /component_1
     dataset    /component_2
     dataset    /group_member
     group      /keys
     dataset    /keys/mach
     dataset    /keys/member
     dataset    /row
     group      /scalars
     dataset    /scalars/cl
     group      /supports
     group      /supports/s0
     dataset    /supports/s0/cell
     group      /supports/s0/cell_arrays
     dataset    /supports/s0/cell_arrays/region
     dataset    /supports/s0/cell_connectivity
     dataset    /supports/s0/cell_offsets
     dataset    /supports/s0/cell_plus_one
     dataset    /supports/s0/cell_types
     dataset    /supports/s0/coordinates
     dataset    /supports/s0/index
     dataset    /supports/s0/node
     group      /supports/s0/node_arrays
     dataset    /supports/s0/node_arrays/pressure
     }
    }

Ten of those datasets are dimension scales: /row, /component_1,
/component_2, /group_member, /category_member, /category_region and,
inside the support, node, cell, cell_plus_one and index. The order
`h5dump` prints is the link name order, which HDF5 keeps by itself;
nothing in the format depends on it.

The root group
--------------

    /
      created               "2026-09-19T00:00:00Z"   string, size 20
      format                "mestra/0"               string, size 8
      writer                "mestra examples 0"      string, size 17
      aligned               1                        int8
      generalisation_group  "member"                 string, size 6

`aligned` is 1 because the file declares one support. There is
therefore no /row_support dataset, and a reader may take every row to
be on s0 without looking further.

The dimension scales at the root
--------------------------------

    /row               (scale)  >f4  shape (2)  max (unlimited)
                                chunk (1)
    /component_1       (scale)  >f4  shape (1)
    /component_2       (scale)  >f4  shape (2)
    /group_member      (scale)  >f4  shape (2)
    /category_member   (scale)  >f4  shape (2)
    /category_region   (scale)  >f4  shape (2)

Each carries CLASS = "DIMENSION_SCALE" and NAME = the 63-character
sentence of section 21, for example, for /row:

    "This is a netCDF dimension but not a netCDF variable.         2"

That sentence is the same in every scale except for the number, so the
dimension's name is the scale's link name, `row`, and never its NAME
attribute. This is the one place a reader goes wrong quietly.

The category tables
-------------------

    /categories/member   string size 6  shape (2)  dim: category_member
      values: "wing_a", "wing_b"
    /categories/region   string size 6  shape (2)  dim: category_region
      values: "inlet", "outlet"

"inlet" is five bytes in a size-6 dataset, so it is stored as
`inlet\0`. A reader strips trailing NUL bytes and then decodes UTF-8.
Category ids are the positions: wing_a is 0, wing_b is 1.

The keys
--------

    /keys/mach      <f8  shape (2)  max (unlimited)  chunk (2)
                    dim: row
      role     "condition"   string, size 9
      units    "1"           string, size 1
      lower    0.1           float64
      upper    0.9           float64
      values:  0.40, 0.80

    /keys/member    <i4  shape (2)  max (unlimited)  chunk (2)
                    dim: row
      role     "group"       string, size 5
      category "member"      string, size 6
      values:  0, 1

`member` is the unit of generalisation, named by the root attribute.
Its values are category ids, so row 0 is wing_a and row 1 is wing_b.
The chunk is two rows because the default of section 23 is capped at
the row count: one row of `mach` is 8 bytes, 1 MiB of rows would be
131072 of them, and there are 2.

The scalar
----------

    /scalars/cl     <f8  shape (2)  max (unlimited)  chunk (2)
                    dim: row
      units    "1"           string, size 1
      source   "data"        string, size 4
      values:  0.25, 0.55

A scalar has one dimension, `row`, and no component dimension.

The support
-----------

    /supports/s0
      kind        "mesh"     string, size 4
      n_nodes     6          int64
      n_cells     2          int64
      support_id  "96df395d80ef548444562292de441525ba0b5c8ad00a8dadf
                   f19a19c943936c7"          string, size 64

    /supports/s0/node           (scale)  >f4  shape (6)
    /supports/s0/cell           (scale)  >f4  shape (2)
    /supports/s0/cell_plus_one  (scale)  >f4  shape (3)
    /supports/s0/index          (scale)  >f4  shape (8)

    /supports/s0/cell_types         <u1  shape (2)  dim: cell
      values: 9, 9
    /supports/s0/cell_offsets       <i8  shape (3)  dim: cell_plus_one
      values: 0, 4, 8
    /supports/s0/cell_connectivity  <i8  shape (8)  dim: index
      values: 0, 1, 4, 3, 1, 2, 5, 4

Code 9 is a quadrilateral and takes four nodes. Cell 0 is
connectivity[0:4] = 0, 1, 4, 3 and cell 1 is connectivity[4:8] =
1, 2, 5, 4. The last offset is 8, which is the length of the
connectivity. The support_id is the SHA-256 of 98 bytes: the node
count as one int64, then the two cell type bytes, then the three
offsets and the eight connectivity values as int64, all
little-endian. Section 24 works it through.

    /supports/s0/coordinates  <f8  shape (2, 6, 2)
                              dims: group_member, node, component_2
      role        "coordinates"    string, size 11
      varies      "group:member"   string, size 12
      units       "m"              string, size 1
      components  2                int64
      source      "data"           string, size 4
      values, instance 0 (wing_a), node 0 to 5:
        (0.0, 0.0) (1.0, 0.0) (2.0, 0.0)
        (0.0, 1.0) (1.0, 1.0) (2.0, 1.0)
      values, instance 1 (wing_b), node 0 to 5:
        (0.0, 0.0) (1.5, 0.0) (3.0, 0.0)
        (0.0, 1.0) (1.5, 1.0) (3.0, 1.0)

The geometry varies along the family, not along the row, so the
leading dimension is `group_member` and not `row`. Instance i is
category id i: instance 0 is wing_a and instance 1 is wing_b. A row's
instance is the value of /keys/member in that row, used directly as an
index. The connectivity is shared, which is what makes this one
support and the file aligned.

    /supports/s0/node_arrays/pressure  <f8  shape (2, 6, 1)
                              max (unlimited, 6, 1)  chunk (2, 6, 1)
                              dims: row, node, component_1
      role        "field"     string, size 5
      varies      "row"       string, size 3
      units       "Pa"        string, size 2
      components  1           int64
      source      "data"      string, size 4
      values, row 0, node 0 to 5:  101, 102, 103, 104, 105, 106
      values, row 1, node 0 to 5:  201, 202, 203, 204, 205, 206

The component dimension is present with length 1, because it always
is. The chunk covers both non-row extents in full, so reading row 1 of
pressure reads no part of any other slot.

    /supports/s0/cell_arrays/region  <i4  shape (2, 1)
                              dims: cell, component_1
      role        "label"     string, size 5
      varies      "none"      string, size 4
      components  1           int64
      source      "data"      string, size 4
      category    "region"    string, size 6
      values, cell 0 and 1:  0, 1

The label is on cells, does not vary, and names a category table, so
cell 0 is "inlet" and cell 1 is "outlet". A label without a `category`
attribute would carry its own ids instead, CAD face ids for example,
and they would not have to start at 0.

Values to check a reader against
--------------------------------

  /supports/s0/node_arrays/pressure  row 1, node 3, component 0   204
  /supports/s0/coordinates           instance 1, node 2, comp 0   3.0
  /keys/mach                         row 1                        0.80
  /scalars/cl                        row 0                        0.25
  /supports/s0/cell_connectivity     index 5                      2

A MATLAB reader returns pressure as 1 by 6 by 2 and coordinates as 2
by 6 by 2, because its natural order is the reverse. That is correct
and expected: what both readers must agree on is the value at (row 1,
node 3, component 0), found by the dimension names and never by the
axis positions.

What the validator says
-----------------------

Nothing. No error and no warning: one support, so no W05; every key
value inside its bounds, so no W04; no non-finite value, so no W03;
"1", "m" and "Pa" all parse, so no W10.


File two: affine_zero_rows.mes
==============================

No rows. Matching support_id attributes declare the same structural
support as file one. These examples use known corresponding nodes;
matching ids alone would not establish correspondence between independent
producers. Verifying an id against stored arrays still requires reading
those arrays. Two slots, one scalar and one node array, are served by one
`affine` callable. Key columns declare bounds and carry no data; those
bounds are not a model-accuracy certificate.

Object list
-----------

    HDF5 "affine_zero_rows.mes" {
    FILE_CONTENTS {
     group      /
     group      /callables
     group      /callables/m1
     dataset    /callables/m1/keys
     dataset    /callables/m1/mestra_keys_d0
     group      /callables/m1/outputs
     group      /callables/m1/outputs/cl
     dataset    /callables/m1/outputs/cl/A
     dataset    /callables/m1/outputs/cl/b
     dataset    /callables/m1/outputs/cl/mestra_A_d0
     dataset    /callables/m1/outputs/cl/mestra_A_d1
     dataset    /callables/m1/outputs/cl/mestra_b_d0
     dataset    /callables/m1/outputs/cl/mestra_shape_d0
     dataset    /callables/m1/outputs/cl/shape
     group      /callables/m1/outputs/pressure
     dataset    /callables/m1/outputs/pressure/A
     dataset    /callables/m1/outputs/pressure/b
     dataset    /callables/m1/outputs/pressure/mestra_A_d0
     dataset    /callables/m1/outputs/pressure/mestra_A_d1
     dataset    /callables/m1/outputs/pressure/mestra_b_d0
     dataset    /callables/m1/outputs/pressure/mestra_shape_d0
     dataset    /callables/m1/outputs/pressure/shape
     dataset    /component_2
     group      /keys
     dataset    /keys/alpha
     dataset    /keys/mach
     dataset    /row
     group      /scalars
     group      /scalars/cl
     group      /supports
     group      /supports/s0
     dataset    /supports/s0/cell
     dataset    /supports/s0/cell_connectivity
     dataset    /supports/s0/cell_offsets
     dataset    /supports/s0/cell_plus_one
     dataset    /supports/s0/cell_types
     dataset    /supports/s0/coordinates
     dataset    /supports/s0/index
     dataset    /supports/s0/node
     group      /supports/s0/node_arrays
     group      /supports/s0/node_arrays/pressure
     }
    }

Two things to notice. /scalars/cl and
/supports/s0/node_arrays/pressure are groups, not datasets: that is
how a slot says its `source` is a callable, and it works whether the
file has rows or not. And there is no /component_1 scale, because no
dataset in this file has a component dimension of length 1; the
pressure slot declares its width in its `components` attribute
instead.

The root group
--------------

    /
      created  "2026-09-19T00:00:00Z"   string, size 20
      format   "mestra/0"               string, size 8
      writer   "mestra examples 0"      string, size 17
      aligned  1                        int8

    /row          (scale)  >f4  shape (0)  max (unlimited)  chunk (1)
    /component_2  (scale)  >f4  shape (2)

There is no `generalisation_group` because the file declares no group
key. `row` has length 0 and is unlimited, which is what makes this a
legal netCDF-4 file rather than one with an illegal zero-length fixed
dimension, and what lets rows be appended later.

The keys
--------

    /keys/alpha  <f8  shape (0)  max (unlimited)  chunk (1)  dim: row
      role   "condition"   string, size 9
      units  "degree"      string, size 6
      lower  -2.0          float64
      upper  10.0          float64

    /keys/mach   <f8  shape (0)  max (unlimited)  chunk (1)  dim: row
      role   "condition"   string, size 9
      units  "1"           string, size 1
      lower  0.1           float64
      upper  0.9           float64

The chunk is one row because the row count is zero. The bounds are the
domain: a caller asking for mach 1.2 is extrapolating, and a generic
tool can say so from the file alone.

The slots
---------

    /scalars/cl                        a group
      units   "1"            string, size 1
      source  "callable:m1"  string, size 11
      output  "cl"           string, size 2

    /supports/s0/node_arrays/pressure  a group
      role        "field"        string, size 5
      varies      "row"          string, size 3
      units       "Pa"           string, size 2
      components  1              int64
      source      "callable:m1"  string, size 11
      output      "pressure"     string, size 8

`source` names the callable and `output` names which of its outputs
fills this slot. Both slots name m1, so one callable serves them
both.

The support
-----------

Identical to file one's, with one difference: the coordinates do not
vary, so they have no leading dimension.

    /supports/s0
      kind, n_nodes, n_cells as before
      support_id  "96df...36c7", the same 64 characters as file one

    /supports/s0/coordinates  <f8  shape (6, 2)
                              dims: node, component_2
      role        "coordinates"  varies "none"  units "m"
      components  2              source "data"
      values, node 0 to 5:
        (0.0, 0.0) (1.0, 0.0) (2.0, 0.0)
        (0.0, 1.0) (1.0, 1.0) (2.0, 1.0)

    /supports/s0/cell_types, cell_offsets, cell_connectivity
        exactly as in file one

The support_id is the same because it hashes the node count and the
cells and not the coordinates. Matching the attributes is a structural
identity comparison; it neither verifies the digest against stored arrays
nor proves physical correspondence or matching geometry.

The callable
------------

    /callables/m1
      type  "affine"                              string, size 6
      repr  "affine(mach, alpha -> cl, pressure)" string, size 35

    /callables/m1/keys  string size 5  shape (2)  dim: mestra_keys_d0
      values: "mach", "alpha"

`keys` is the callable's declared key order, and it is its own order,
not the file's. The file's key order, which section 26 fixes as the
names under /keys sorted by their bytes, is alpha then mach. The
callable takes the columns it names in the order it names them.

    /callables/m1/outputs/cl/A      <f8  shape (1, 2)
                                    dims: mestra_A_d0, mestra_A_d1
      values: 2.0, 0.1
    /callables/m1/outputs/cl/b      <f8  shape (1)
                                    dim: mestra_b_d0
      values: 0.05
    /callables/m1/outputs/cl/shape  <i8  shape (0)  max (unlimited)
                                    chunk (1)  dim: mestra_shape_d0
      values: none; it is the empty array

    /callables/m1/outputs/pressure/A      <f8  shape (6, 2)
                                    dims: mestra_A_d0, mestra_A_d1
      values, row by row:
        (1.0, 0.0) (2.0, 0.0) (3.0, 0.5)
        (4.0, 0.5) (5.0, 1.0) (6.0, 1.0)
    /callables/m1/outputs/pressure/b      <f8  shape (6)
                                    dim: mestra_b_d0
      values: 0.0, 0.1, 0.2, 0.3, 0.4, 0.5
    /callables/m1/outputs/pressure/shape  <i8  shape (2)
                                    dim: mestra_shape_d0
      values: 6, 1

The dimension scales inside a dictionary are named after their
dataset, `mestra_A_d0` and not `d0`, because `A` and `shape` are in
one group and would otherwise both want a dimension called `d0` with
two different lengths. The reserved prefix is also how a reader
reconstructing the dictionary knows which members are the container's:
it skips every name beginning with `mestra_`, and the dictionary that
comes back is

    {"keys": ["mach", "alpha"],
     "outputs": {
       "cl":       {"A": [[2.0, 0.1]],
                    "b": [0.05],
                    "shape": []},
       "pressure": {"A": [[1.0, 0.0], [2.0, 0.0], [3.0, 0.5],
                          [4.0, 0.5], [5.0, 1.0], [6.0, 1.0]],
                    "b": [0.0, 0.1, 0.2, 0.3, 0.4, 0.5],
                    "shape": [6, 1]}}}

with `shape` an int64 array in both entries, empty in the first.
`type` and `repr` are not in it: they are the container's attributes
on the same group, which is why a dictionary may not have `type` or
`repr` at its top level.

Evaluating it
-------------

`shape` is [6, 1] for pressure, so n_out_flat is 6, and it is empty
for cl, so n_out_flat is the empty product, 1. On the one-row keys
table mach = 0.5, alpha = 4.0, with x = (0.5, 4.0) in the declared
order:

    cl        2.0*0.5 + 0.1*4.0 + 0.05                = 1.45
    pressure  1.0*0.5 + 0.0*4.0 + 0.0                 = 0.5
              2.0*0.5 + 0.0*4.0 + 0.1                 = 1.1
              3.0*0.5 + 0.5*4.0 + 0.2                 = 3.7
              4.0*0.5 + 0.5*4.0 + 0.3                 = 4.3
              5.0*0.5 + 1.0*4.0 + 0.4                 = 6.9
              6.0*0.5 + 1.0*4.0 + 0.5                 = 7.5

Reshaped to [6, 1] in C order and given the row axis, pressure comes
back as (1, 6, 1) and cl as (1,). Writing those out turns this file
into one like file one, with `source` = "data" everywhere, the same
support_id, and one row.

What the validator says
-----------------------

Nothing. A file with no rows and callable slots is valid, and so is
the same file with rows added to the key columns: what decides whether
a slot holds data is its `source` and never the row count.


Checking an implementation against these two
============================================

  1. Compute the support_id from the file's own arrays and compare it
     with the attribute. If it matches in both files, the hash rule,
     the byte order and the dtypes are right.
  2. Read pressure at (row 1, node 3, component 0) in file one and
     get 204. If the answer is 105 the axes were taken by position.
  3. Read the dimension names of pressure and get row, node,
     component_1. If they all come back as the same sentence, they
     were read from the NAME attribute instead of the link name.
  4. Open both files with a netCDF-4 reader and list the dimensions.
     Both open, and the dimension names are the ones above.
  5. Round-trip the dictionary of m1 and compare against the one
     written above, with `shape` still an integer array and still
     empty for cl.
  6. Evaluate m1 at mach = 0.5, alpha = 4.0 and get 1.45 and
     0.5, 1.1, 3.7, 4.3, 6.9, 7.5.

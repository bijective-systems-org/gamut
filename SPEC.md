# The Gamut file format, version 1

A Gamut file holds one parametric simulation study, or one model fitted
to such a study, and says what every number in it is. This document is the
format's definition: the libraries in this repository implement it, and
anyone may write another implementation from it.

Part I says what a file holds, in plain terms. Part II is the layout on
disk. Part III is validation and versions. A file that breaks a rule is
invalid, and the validator names the rule it breaks (§16): `E` rules are
errors, `W` rules warnings.

---

# Part I. What a file holds

## 1. Purpose

A file holds one parametric simulation study, or one model of such a
study, and says what every number is: its name, units, role and where it
lives. A study is a set of runs of a simulation over design parameters and
operating conditions; each run produces single-number results and,
optionally, fields on a mesh. The format is for sharing studies between
people and tools, for training models on them, and for any tool that
works across many runs, including solvers for parametric studies that
read zones and boundary conditions from it.

What the format adds to a folder of VTK files: one file per study; the
run table with units, roles, status and splits; compression and reads of
one run, or one region of every run, without reading the rest; and, for
runs that share a mesh, every field as one block of runs × nodes, so that
node k is the same point in every run.

## 2. Kinds of file

Every file is a **data file** or a **model file** (root attribute `kind`).

| Kind | Holds | Inputs need | Results are |
|---|---|---|---|
| data | runs | values | stored |
| model | no runs; one or more models | bounds (the model's domain) | computed by a model on request |

Evaluating a model file on a table of inputs produces a data file with the
same results.

A data file has one of three **types**, read from its content and never
declared:

| Type | The file has | Can do |
|---|---|---|
| table | no mesh | the run table |
| shared mesh | one mesh that every run uses; cells optional (without cells it is a point cloud) | everything below, plus reads of one node or region across every run, the whole field as one runs × nodes block, and comparisons node by node across runs |
| changing mesh | a mesh per run, or per group of runs (each geometry of a family) | one run's fields, the run table; no operation that needs node k to be the same point in every run |

Operations that need correspondence exist only for the shared mesh; a
library refuses them on a changing mesh with a message that says so.

Add-ons, also read from content, are reported beside the type: *time* (a
time parameter), *gradients* (a derivative), *uncertainty* (a std or a
quantile).

## 3. The run table

A row is one run, or one saved time step of a run (§3.3). Rows have no
required order.

### 3.1 Row ids

The library gives every row an id when it is written: an int64, unique in
the file, never reused. Ids start at 0; an append continues from one more
than the largest id in the file. A subset written to a new file keeps the
ids it had, so a row can be traced to the study it came from. A producer's
own run names go in a label (§3.4).

### 3.2 Parameters

A parameter is a per-row number that locates a run in the sampled space.
It has:

- `role`: `design` (the shape of the thing: a geometry or design
  variable), `condition` (how it is operated: Mach, incidence,
  altitude, load) or `time` (§3.3). Roles exist because each changes a
  tool's default: a geometry model takes the design parameters; time
  animates and groups rows; a trainer holds out by group.
- `units`, required (§3.7).
- `lower`, `upper`: optional in a data file; required in a model file,
  where they are the model's domain.

Values are float64, or int64 for counts.

### 3.3 Time

Each saved time is a row. A time parameter has role `time`; a group label
says which run each row belongs to, and the time parameter names that
label in `run_group`. With `run_group` a viewer animates one run by its
rows in time order, and a trainer holds out whole runs. Runs may differ in
length and in their save times; rows of one run need not be contiguous.
Two rows of one run at the same time are reported (W9). A single transient
run needs no `run_group`.

A history sampled at the same times in every run is not a separate case:
it is rows too.

### 3.4 Labels

A label is a per-row value that names rather than measures. It is stored as
an integer code per row with a table of names (the category table): code c
names entry c of the table. It is read back as names. Roles:

| Role | Meaning |
|---|---|
| `group` | Rows that belong together: one geometry of a family, one transient run, one case |
| `categorical` | Any other category: fidelity, solver, turbulence model, configuration, a yes/no switch |
| `status` | Whether a row's results are fit to use; `converged`, `failed` and `partial` are recommended; rows not `converged` are reported (W2) and skipped by training by default |
| `split` | A split the producer publishes with the data, such as a benchmark's official train and test sets |

At most one `status` label. Any number of the others. A yes/no value is a
`categorical` label whose table is `false`, `true` (codes 0 and 1); a
library accepts booleans and writes that table itself.

**Unit of generalisation.** The root may name one group label in
`generalisation_group`: the group a fair test holds out whole, such as the
geometry of a family. A published split that places rows of one such group,
or of one run (`run_group`), on both sides is reported (W1).

### 3.5 Scalars

A scalar is a result with one value per row (lift coefficient, peak heat
flux), with units. Values are float32 or float64, kept as the producer
gives them. A vector quantity per row is one scalar per component; scalars
do not declare vectors.

### 3.6 Constants

A constant is one value for the whole file, with units: a reference area, a
reference length, a fixed freestream value. A constant vector is one
constant per component.

### 3.7 Units

Units are strings in the UDUNITS-2 grammar that CF uses (`Pa`, `m s-1`,
`W m-2`, `1` for dimensionless; §13). They are required on every
parameter, scalar, constant, field and on coordinates; a string that does
not parse is an error (E7). Labels carry none. A library may convert
values to other units when reading and when appending; the file stores
the units the producer declared.

### 3.8 Missing values

A result a row does not have (a failed run, withheld test outputs) is NaN;
it is reported with the row and the name (W3). Parameters and labels are
never missing.

## 4. The shared mesh

### 4.1 The mesh

A shared mesh is nodes with coordinates of one to three axes (`x`, `y`,
`z`), and optionally cells. Cells use VTK cell codes and VTK node order;
mixed types are allowed; the codes allowed are listed in §15 (triangles,
quadrilaterals, tetrahedra, hexahedra, wedges, pyramids, polygons, lines,
vertices and the quadratic forms). Boundary faces may be 2-D cells in the
same mesh as a volume. A mesh without cells is a point cloud: pressure
taps, probes, spanwise stations.

### 4.2 How often the mesh changes

Results are always one value set per run. The mesh is stored as often as
it changes, declared by `per` on the mesh:

| `per` | Meaning | Example |
|---|---|---|
| `fixed` | one geometry for every run | a condition sweep on one mesh |
| `group:<label>` | one geometry per category of a group label | a family of shapes meshed with one topology, run at several conditions per member |
| `run` | one geometry per run | a mesh that deforms with every run |

Connectivity and mesh labels never change in a shared mesh; `per` applies
to coordinates only. Each geometry is an *instance*: with `per = run`
instance r is row r; with `per = group:<label>` instances are numbered in
the order their category first appears in the file, and `row_instance`
records each row's instance (every row of one category has the same one).
A library reads coordinates per run whatever `per` is: asking for run r
returns run r's geometry. Coordinates are absolute positions, never
displacements.

### 4.3 Mesh labels

A mesh label is an integer per node or per cell that describes the mesh:
zones, boundary patches, materials, CAD faces. It may name a category table
(the same codes-and-names pattern as row labels); without one, its values
are their own names, any integer. In a shared mesh, mesh labels are fixed:
node k is the same point in every run, so its zone is too (a per-run
integer that varies is a result). A boundary
condition is marked by a cell label on boundary faces (`patch`: `inlet`,
`wall`, `outlet`); its values are parameters (an inlet velocity per run)
or fields on those faces.

### 4.4 Fields

A field is a result with one value per node, or one per cell, for every
run, with units. Where it lives is declared by where it is written (node
fields and cell fields are separate groups) and checked against the mesh's
node or cell count; it is never inferred from a length. A node field and a
cell field never share a name (below).

Fields have one component. A vector or tensor quantity is one field per
component, and the components declare that they belong together:
`vector` names the quantity and `axis` names the component (`x`, `y`, `z`
for a vector; tensors are not declared in version 1). Names are free:
`u`, `v`, `w` with `vector = velocity` is as good as `velocity_x`. The
fields of one vector have one location, one set of units and distinct
axes, and only axes the coordinates have (E13). Tools use the declaration
to draw arrows, compute magnitudes and write VTK vectors.

**Names are unique in a file.** No two of its parameters, labels, scalars,
constants, fields and mesh labels share a name (E8), so every call can take
a bare name. A tool importing data that has a point array and a cell array
of one name renames one and says so.

Values are float32 or float64, kept as given.

### 4.5 Correspondence and support id

The producer establishes that node k is the same point in every run (a
morphing tool such as TopoLink, a fixed-topology mesher, a solver on one
mesh). The file records the claim structurally: node count and
connectivity are stored once. It cannot check physical meaning; two
producers can number one mesh differently. The mesh carries `support_id`,
a SHA-256 digest of its node count, its cells and, for a point cloud with
fixed coordinates, its coordinates (§14). The id decides "same mesh"
across files: a model and the study it predicts, two studies combined.

## 5. The changing mesh

A changing mesh stores one mesh *instance* per run (`per = run`) or per
category of a group label (`per = group:<label>`, for instance each
geometry of a remeshed family, run at several conditions), numbered as
for the shared mesh (§4.2). Each instance has its own nodes, cells and
mesh labels. Fields are one value set per run,
on that run's instance. Instances and fields are stored end to end, with
offsets saying where each instance and each run's values start (§10.4), the
arrangement VTKHDF uses for meshes that change from step to step.

Nothing in a changing-mesh file claims that node k of one instance relates
to node k of another. Turning a changing-mesh study into a shared-mesh one
needs a correspondence between the instances, which a mapping or morphing
tool produces.

## 6. Relations: uncertainty and derivatives

A result may declare that it describes another result, named in `of`.
There are two kinds; anything else (an RMS, a time average, a maximum) is
another result with a descriptive name.

**Uncertainty of a result** (`statistic`):

| `statistic` | Means | Also |
|---|---|---|
| `std` | the standard deviation of `of`: a measured spread (an unsteady run's fluctuation, repeated tests, a Gaussian model's sigma) | never negative (W10) |
| `quantile` | the value of `of` at percentile `q`: `q = 0.05` is the value 5 % of outcomes fall below | `q` in (0, 1); a symmetric interval is two quantiles |

Either may carry `method`: one line on how it was obtained. Its units
string equals that of `of`.

**Derivative of a result** (`with_respect_to`): the partial derivative of
`of` with respect to a parameter, or with respect to node position
(`with_respect_to = coordinates`, with `axis` naming the coordinate). A
derivative of a scalar with respect to node position is a node field per
axis: an adjoint shape sensitivity. A gradient over many parameters is one
derivative result per parameter. Units are not checked.

A relation result has the location of its `of` (a scalar for a scalar, a
field at the same location for a field), except a derivative with respect
to node position, which is a node field whose `of` is a scalar. `of` names
a scalar or field that is not itself a relation. A result carries
`statistic` or `with_respect_to`, not both.

Tools act on relations without knowing names: a viewer draws error bars
from a `std` or a pair of quantiles; gradient-enhanced kriging collects the
derivatives of an output; a Gaussian process takes a `std` as per-run noise.

## 7. Model files

### 7.1 What a model file holds

A model file has no runs. It holds:

- the inputs a model takes: parameters with required bounds (the domain),
  labels with their tables, and, when a model reads geometry, the mesh's
  coordinates;
- the results it produces: scalars and fields, each a zero-length dataset
  of the shape and dtype it has in a data file, naming the model and the
  output that computes it, with relations (a model serves quantiles, a std
  and derivatives the same way);
- the mesh its fields live on (a shared mesh; its coordinates are stored,
  or computed by a model for a model of the geometry itself);
- constants;
- one or more models under `/models/<id>`.

Which data a model was trained on may be recorded in the root attribute
`trained_on`: the `file_id` (§8) of each data file, separated by spaces.

### 7.2 A model

A model has a `type`, naming the software that runs it; `inputs`, the
public list of what it reads (parameters, labels, and `coordinates`); and
its own numbers, stored as plain data by the codec of §12. The format
standardizes the interface, never the internals: only the software that
owns the type interprets the numbers. A file never holds executable code.

Licensing is not part of the format or its libraries. Running a model needs
its owning software and whatever licence that software requires; a model
of a user's own type runs with the user's registered code; the built-in
`nearest` runs everywhere.

### 7.3 The plug-in interface

A model type is registered with a library (in Python and MATLAB at least)
as three operations:

- **load**: from the stored numbers to a working model;
- **call**: given an input table and the outputs wanted, return each
  output's values and, when asked, its std, quantiles and derivatives;
- **save**: from a working model to numbers to store.

The input table maps each input to an array whose first axis is the row:
`(row)` for a parameter or a label code, `(row, node, axis)` for
coordinates. An output's values are `(row)` for a scalar and `(row, node)`
or `(row, cell)` for a field; a std or quantile has the shape of its
values; a derivative with respect to a parameter has the shape of its
values; a derivative of a scalar with respect to node position is
`(row, node, axis)`.

### 7.4 Evaluation

Evaluating a model file on an input table of n rows yields a data file of
n rows: the inputs as parameters and labels, the constants, the mesh, and
every result filled by calling its model. The mesh's coordinates are per
run in the result when a model computes them or when the caller supplies
coordinates (a model that reads `coordinates` evaluated on new
geometries); otherwise they are the model file's stored coordinates, and a
model that reads `coordinates` receives those. The data file records the model file's `file_id` in
`evaluated_from`. An input outside its bounds is reported (W4) and
evaluated; refusing is the caller's choice.

The input table maps names to columns of one length n: a parameter by its
values (an int64 parameter accepts integers), a label by its names, each in
the model file's table (a name outside it is an error), and `coordinates`,
when a model reads them, as n × nodes × axes in the coordinates' units.
The data file's rows get ids 0 to n − 1. A label's codes are the model
file's.

### 7.5 The built-in model: nearest neighbour

Type `nearest` returns, for each input row, the outputs of the closest
stored point. It exists so that model files can be tested in every
language with no proprietary software, and as a baseline ("the closest run
we have"). Its numbers (§12):

- `columns`: the input names, in the column order of `x`;
- `lower`, `upper`: one bound per column;
- `x`: float64, (points, columns);
- `outputs`: a dictionary with one array per output, float64, first axis
  points: `(points)` for a scalar, `(points, node)` or `(points, cell)` for
  a field.

Inputs are parameters only; `columns` holds exactly the model's `inputs`,
and `lower` and `upper` equal those parameters' bounds (E17); there is at
least one point (E17). Int64 inputs are taken as float64. For a query row q
and point i, with t_j = (q_j − x_ij) / (upper_j − lower_j) rounded to
float64 before it is squared, the distance is t_1² + t_2² + … summed left
to right in column order, each step rounded to float64, with no fused
multiply-add; a column whose `upper_j = lower_j` is left out. A non-finite
value in a used column of the query gives NaN outputs for that row. The
nearest point is the one with the smallest distance; ties go to the lowest
i. Outputs are float64 values only: no std, quantiles or derivatives.

## 8. Metadata

The root carries `writer`, `created` (ISO 8601 UTC) and `file_id` (a
random UUID, lower-case, written once when the file is created), and may
carry `title`, `license` (an SPDX identifier or a URL), `references` (a
citation or DOI) and `source` (the program that produced the data), with
the meanings the Attribute Convention for Data Discovery gives them, so
that dataset catalogues can read them. `/notes` holds any other free-form
public attributes; nothing depends on them. `/private` holds a producer's
own records in any form; readers copy it and never interpret it. Public
information is never only in `/notes` or `/private`.

---

# Part II. On disk

## 9. Container

### 9.1 HDF5 laid out as netCDF-4

A file is HDF5 constrained so that it is also a valid netCDF-4 file: named
dimensions as dimension scales; attributes as strings or numbers; groups
for structure; and no compound types, object references, enumerations or
variable-length types in the data and attributes this format defines. The
dimension-scale machinery (`DIMENSION_LIST`, `REFERENCE_LIST`) is exempt;
readers ignore it, and also `CLASS`, `NAME`, `DIMENSION_LABELS`,
`_Netcdf4Dimid`, `_Netcdf4Coordinates`, `_nc3_strict` and `_NCProperties`.
The extension is `.gamut`; the root attribute `format` decides, not the
extension.

### 9.2 Attributes

Every attribute this specification names has one encoding, scalar
dataspace:

| Kind | Encoding |
|---|---|
| integer | int64 little-endian |
| float | float64 little-endian; bounds and `q` finite |
| string | fixed-length, UTF-8 character set, null-padded; size the UTF-8 byte length (1 for the empty string); no NUL byte inside |

Two exceptions: `_QuantizeBitRoundNumberOfSignificantBits` (§11.3) may be
int32 as netCDF-C writes it, and the null value inside model data (§12) is
a string attribute holding a NUL byte. A list of names in an attribute
(`inputs`, `trained_on`) is one string with names separated by single
spaces; names hold no spaces.

### 9.3 Names

Every group, dataset, attribute and dimension name is a legal netCDF-4
name: not empty; no `/` or NUL; letters, digits, `_`, `-`, `.`, `+`; first
character a letter, digit or underscore; no leading or trailing space.
Names a producer chooses must not begin with `gamut_`, and in the root
must not be `row`, `coordinates`, `categories`, `mesh`, `models`, `notes`,
`private` or `VTKHDF`, or begin with `category_` (E8). Names are unique in
the file (§4.4).

### 9.4 Dimension scales

Every axis of every dataset has exactly one dimension scale attached
(E19), named as §10 gives. A scale with no values is written as netCDF-C
writes a dimension without a coordinate variable: one-dimensional,
float32 big-endian, no values written; `CLASS = "DIMENSION_SCALE"`;
`NAME` = the 53 characters `This is a netCDF dimension but not a netCDF
variable.` followed by the length right-justified in ten columns (C
format `"%s%10d"`); writers may update the length when the scale grows,
and readers ignore `NAME`. The `row` scale is a coordinate variable: int64, the
row ids as values, `NAME = "row"`. Every scale is created with attribute
creation order tracked and indexed and object time tracking off. A
dimension's name is the scale's link name, never its `NAME`; a reader
resolves attached scales through a map from object address to link name
built during its own walk, never by asking HDF5 for a path. A scale is
unlimited when the layout lets its dimension grow (§10) and fixed
otherwise, and its extent equals the extent of every axis attached to it:
a writer extends scales as it appends (E19).

### 9.5 Strings in datasets

A fixed-length string dataset is UTF-8, null-padded, sized to its longest
element in bytes (1 when all are empty); wider is legal and reported (W7).
A reader strips trailing NULs and decodes UTF-8. A string that is not
valid UTF-8 or holds a NUL is an error (E4). A producer that wants MATLAB
to read every string keeps names, table entries and labels to ASCII.

### 9.6 Reading safely

A reader treats a file as untrusted. It follows only hard links; a soft or
external link is an error and is never opened (E22). It caps recursion over
groups and model data at a depth it states (64 recommended), an eager
read at an element count it states (2³¹ recommended), and the chunks one
read touches when its chunks are smaller than §11.4's defaults (2²⁰
recommended: libraries keep state per chunk, so a file of tiny chunks makes
a small read costly); beyond any, and for an object it
cannot read, it reports E23 with the path and goes on. Every count taken
from the file is checked against these caps before it sizes a buffer.
Opening a file reads structure and attributes only, never field values or
model data.

## 10. Layout

`?` marks an optional attribute or object.

### 10.1 Every file

    /                          format = "gamut/1", kind (data | model),
                               writer, created, file_id,
                               title?, license?, references?, source?,
                               generalisation_group? (data), trained_on? (model),
                               evaluated_from? (data)
    /row                       (row) int64, unlimited: the row ids
    /category_<t>              dimension scales, unlimited
    /<parameter>               (row) float64 | int64
                               role (design | condition | time), units,
                               lower?, upper?, run_group? (time only)
    /<label>                   (row) int32 | int64
                               role (group | categorical | status | split),
                               category (the table's name)
    /<scalar>                  (row) float32 | float64
                               role = scalar, units, relation attributes?,
                               rounding attribute?, coordinates? (CF),
                               model and output (model file only)
    /<constant>                () float32 | float64 | int64
                               role = constant, units
    /categories/<t>            (category_<t>) fixed-length strings
    /mesh?                     §10.2 to §10.4
    /models/<id>?              model files only (§10.5)
    /notes?, /private?

Every root dataset or served group carries `role`. Relation attributes are
`of`, `statistic`, `q`, `method`, `with_respect_to`, `axis` (§6). Writers
add a CF `coordinates` attribute to each scalar listing the parameters and
labels, so generic netCDF tools show the run table; nothing depends on it.
A model file has zero rows; its parameters, labels and results are
zero-length datasets carrying their attributes, and a result's `model`
and `output` say what computes it.

### 10.2 Shared mesh

    /mesh                      kind = "shared", per (fixed | run | group:<k>),
                               support_id
      /node, /axis             dimension scales
      /cell, /cell_plus_one, /index    dimension scales (absent without cells)
      /instance                dimension scale, unlimited (per group only)
      /coordinates             fixed: (node, axis); per run: (row, node, axis);
                               per group: (instance, node, axis)
                               float32 | float64, units; model, output (model
                               file whose coordinates a model computes)
      /row_instance            (row) int64 (per group only)
      /cell_types              (cell) uint8           } absent for a
      /cell_offsets            (cell_plus_one) int64  } point cloud
      /cell_connectivity       (index) int64          }
      /node_labels/<name>      (node) int32 | int64; category?
      /cell_labels/<name>      (cell) int32 | int64; category? (absent
                               without cells)
      /node_fields/<name>      (row, node) float32 | float64
                               units, vector?, axis?, relation attributes?,
                               rounding attribute?, model and output (model
                               file only)
      /cell_fields/<name>      the same over (row, cell)

`axis` has length 1, 2 or 3 (E24). `cell_offsets` starts at 0, never
decreases and ends at the length of `cell_connectivity`; cell j uses
`cell_connectivity[cell_offsets[j] : cell_offsets[j+1]]`, whose length is
the node count of its type (§15); every value is in [0, n_nodes) (E10).

### 10.3 Shared mesh in a model file

`per` is `fixed` (stored coordinates) or `run` (coordinates computed by a
model: a zero-length `(row, node, axis)` dataset, filled on evaluation).

### 10.4 Changing mesh

    /mesh                      kind = "changing", per (run | group:<k>)
      /instance_plus_one, /node, /cell, /cell_plus_one, /index, /axis,
      /node_value, /cell_value                         dimension scales
      /instance_nodes          (instance_plus_one) int64: cumulative node
                               counts, starting at 0
      /instance_cells          (instance_plus_one) int64: cumulative cell
                               counts, starting at 0
      /coordinates             (node, axis) float32 | float64, units
      /cell_types              (cell) uint8
      /cell_offsets            (cell_plus_one) int64, into cell_connectivity
      /cell_connectivity       (index) int64, node numbers local to the
                               cell's instance
      /node_labels/<name>      (node) int32 | int64; category?
      /cell_labels/<name>      (cell) int32 | int64; category?
      /row_instance            (row) int64 (per group only)
      /row_node_start          (row) int64: where row r's values start in
                               every node field
      /row_cell_start          (row) int64: the same for cell fields
      /node_fields/<name>      (node_value) float32 | float64; attributes
                               as for a shared mesh
      /cell_fields/<name>      (cell_value) the same

Instance k owns nodes `[instance_nodes[k], instance_nodes[k+1])` and cells
`[instance_cells[k], instance_cells[k+1])`. Row r's instance is r when
`per = run`, and `row_instance[r]` when `per = group:<k>` (instances
numbered by first appearance, §4.2). The rule of §10.2 for `cell_offsets`
holds over the whole of `cell_offsets` here, and node numbers in
`cell_connectivity` are local to the cell's instance. Without cells, every
cell object is absent: `instance_cells`, `cell_types`, `cell_offsets`,
`cell_connectivity`, `row_cell_start`, cell labels and fields, and the
`cell`, `cell_plus_one`, `index` and `cell_value` scales. Whether a mesh
has cells holds for all its instances. Row r's
node values are `[row_node_start[r], row_node_start[r] + n)` where n is its
instance's node count, likewise for cells. Rows' values are stored in row
order with no gaps. `node`, `cell`, `cell_plus_one`, `index`, `instance_plus_one`,
`node_value` and `cell_value` are unlimited. The
offsets and starts must agree (E21).

### 10.5 Models

    /models/<id>               type, inputs, repr?
                               the model's numbers below, by the codec of §12

`inputs` names parameters, labels and `coordinates` (E17). `type`,
`inputs` and `repr` are attributes of the group, not part of the numbers;
the numbers' top level must not use those three names.

## 11. Storage

### 11.1 Dtypes

| Object | Allowed |
|---|---|
| `row` | int64 |
| Parameter | float64, int64 |
| Row label, mesh label | int32, int64 |
| Scalar, constant, field, coordinates | float32, float64 (a constant also int64) |
| Category table | fixed-length UTF-8 |
| `cell_types` / offsets, connectivity, instance and row starts | uint8 / int64 |

All numeric data is little-endian, C order. A library stores results at
the precision it is given and converts only when asked. No dataset has a
user-defined HDF5 fill value or a `_FillValue` attribute; every element is
written.

### 11.2 Compression

gzip, levels 1 to 9, with or without shuffle; nothing else (E20). Writers
compress with shuffle and gzip level 1 by default. Every HDF5 build,
including MATLAB's and Julia's, has these filters.

### 11.3 Rounding

A writer may round a float result's mantissa to fewer bits (round half to
even; NaN and infinities unchanged) and record the bits kept, n, in
`_QuantizeBitRoundNumberOfSignificantBits`, the attribute netCDF-C 4.9
writes for the same BitRound algorithm. The relative error is at most
2⁻⁽ⁿ⁺¹⁾ for normal values. Values stay ordinary floats. Off by default.

### 11.4 Chunking and file space

Every dataset with a dimension that may grow (`row`, `category_<t>`,
`instance`, and in a changing mesh the dimensions §10.4 lists as
unlimited) is chunked (E20); larger fixed datasets may be chunked too, to
be compressed. With T = 262,144 bytes and b the bytes of one entry along
the first axis (dtype size times the other extents):

- **Leading axis grows** (root datasets; category tables; shared-mesh
  fields and coordinates per run or per instance; `row_instance`; a
  changing mesh's `row_node_start` and `row_cell_start`): when b ≤ T the
  chunk holds c = min(512, max(1, ⌊T / b⌋)) entries along the first axis,
  the other axes whole; when b > T it holds one entry and, along the node
  or cell axis, m = min(n, max(1, ⌊T / (dtype size × trailing
  extents)⌋)), other axes whole.
- **Every other chunked dataset** (the other changing-mesh datasets, fixed
  coordinates, cells, mesh labels): max(1, ⌊T / b⌋) entries
  along the first axis, other axes whole.

Readers accept any chunk shape; a chunk larger than these is reported
(W6), a smaller one is not, so appended files draw no warning.

A writer creates files with HDF5's persistent free-space management
(strategy `FSM_AGGR`, persisting, threshold 1) and library version bounds
from the earliest to 1.10, which that needs. A compressed chunk rewritten
larger leaves its old space free, and without tracking that space is lost
when the file closes. Measured (20 float64 columns, 3,000 appends of one
row, the file reopened for each): 32 MB without, 0.49 MB with, the size of
the data; chunks of 32,768 entries without it reached 196 MB. Readers need
HDF5 1.10 or later; netCDF4, xarray and MATLAB R2026a (HDF5 1.14.4) read
such files. Writers also buffer appends to whole chunks within a session.

### 11.5 Appending

Rows can be appended in place: every growable dimension is unlimited, so
new runs may bring new members (a group table grows) or new instances. A
library appends without copying or re-reading the whole file, and checks
the structure and the appended rows. A fixed-length string dataset whose
new values need a wider width is recreated: its scale is detached, the
dataset deleted, recreated and the scale reattached.

## 12. Model data codec

A model's numbers are a nested dictionary whose leaves are numbers,
booleans, strings, numeric arrays, lists of numbers and lists of strings.
They map to the group `/models/<id>`:

| Value | Stored as |
|---|---|
| nested dictionary | a subgroup named by its key |
| integer / float / boolean | an attribute: int64 / float64 / int8 (0 or 1; read back as a boolean) |
| string | a string attribute |
| null | the string attribute whose bytes are exactly `00 6E 75 6C 6C` (a NUL then `null`) |
| numeric array, list of numbers | a dataset in C order, dimension scales `gamut_<dataset>_d<i>` |
| list of strings | a one-dimensional fixed-length string dataset |

Dataset dtypes: int8 (boolean), int32, int64, float64, fixed-length UTF-8.
A zero-dimensional array is written as the number it holds. An array with
a zero extent keeps its dtype, with that axis unlimited. A ragged or mixed
list, a list of dictionaries, a list of nulls, any other dtype and a string
holding NUL are not representable; the writer refuses them (E18). Keys are
legal names not beginning with `gamut_`; a writer visits keys in
ascending order of their UTF-8 bytes; readers do not depend on order. A
reader that does not know a model's type copies the group unchanged.

## 13. Units grammar

A units string parses when it matches this grammar, the UDUNITS-2 grammar
in the forms CF files use, with the power after `^` or `**` allowed to be
any number. Deciding needs no unit database; converting does.

    units      = { sp } product [ shift ] { sp }
    product    = power { [ operator ] power }
    operator   = { sp } ( "*" | "." | "-" | "/" | "per" ) { sp } | sp { sp }
    power      = basic [ integer | ( "^" | "**" ) number ]
    basic      = name | number | "(" units ")"
               | ( "log" | "lg" | "ln" | "lb" ) logref
    logref     = "(" { sp } "re" ( ":" { sp } | sp { sp } ) product { sp } ")"
    shift      = { sp } ( "@" | "since" | "from" | "after" | "ref" ) { sp }
                 ( timestamp | number )
    timestamp  = date [ ( "T" | sp { sp } ) clock [ { sp } zone ] ]
    date       = [ sign ] digit { digit } "-" digit [ digit ] [ "-" digit [ digit ] ]
    clock      = digit [ digit ] ":" digit digit [ ":" digit digit [ "." { digit } ] ]
    zone       = name | sign digit [ digit ] [ [ ":" ] digit digit ]
    number     = [ sign ] ( digit { digit } [ "." { digit } ] | "." digit { digit } )
                 [ ( "e" | "E" ) [ sign ] digit { digit } ]
    integer    = [ sign ] digit { digit }
    name       = letter { letter | digit }
    letter     = "A"–"Z" | "a"–"z" | "_" | "%" | "'" | '"' | any non-ASCII character
    sign       = "+" | "-"
    digit      = "0"–"9"
    sp         = " "

A string is matched from the left, each rule taking as much as it can,
with five fixed readings: a name's trailing digits are its power (`m2` is m
squared, `m2s` one name); an integer power follows its basic directly
(`m-1` is m⁻¹, `m -1` is m times −1, `m+s` does not parse); `per`, `since`,
`from`, `after`, `ref` are operators only where an operator can stand and
as whole words; after `log`, `lg`, `ln`, `lb`, a `(` then `re` and `:` or a
space opens a logref, any other `(` a group; a shift's operand is a
timestamp when one matches. The empty string, a string of spaces, a string
with any space but U+0020, a string over 4096 bytes and one nesting
parentheses deeper than 32 do not parse.

## 14. Support id

`support_id` is the lower-case hexadecimal SHA-256 digest of these bytes,
in order, with nothing between them: `n_nodes` as one int64 little-endian;
`cell_types` as uint8; `cell_offsets` as int64 little-endian;
`cell_connectivity` as int64 little-endian; and, for a point cloud whose
`per` is `fixed`, the coordinates as float64 little-endian in (node, axis)
order (float32 coordinates widened first). A point cloud has no cell bytes.
Worked example: six nodes, two quadrilaterals, `cell_types [9, 9]`,
`cell_offsets [0, 4, 8]`, `cell_connectivity [0, 1, 4, 3, 1, 2, 5, 4]`: 98
bytes beginning `06 00 00 00 00 00 00 00 09 09 00 00`, digest
`96df395d80ef548444562292de441525ba0b5c8ad00a8dadff19a19c943936c7`.

## 15. Cell types

| Code | Cell | Nodes |
|---|---|---|
| 1 | vertex | 1 |
| 3 | line | 2 |
| 5 | triangle | 3 |
| 7 | polygon | 3 or more |
| 9 | quadrilateral | 4 |
| 10 | tetrahedron | 4 |
| 12 | hexahedron | 8 |
| 13 | wedge | 6 |
| 14 | pyramid | 5 |
| 21 | quadratic line | 3 |
| 22 | quadratic triangle | 6 |
| 23 | quadratic quadrilateral | 8 |
| 24 | quadratic tetrahedron | 10 |
| 25 | quadratic hexahedron | 20 |
| 26 | quadratic wedge | 15 |
| 27 | quadratic pyramid | 13 |

Node order within a cell is VTK's for that code. Any other code is an error
(E6); polyhedra are not in version 1, and an importer asks for them to be
exported decomposed.

---

# Part III. Rules and versions

## 16. Validation

A validator reports every finding it can decide, not only the first.
Errors make a file invalid; warnings are reported and the file is accepted.

**Errors**

| Rule | Finding |
|---|---|
| E1 | `format` missing or not `gamut/1`; `kind` missing or not `data` or `model` |
| E2 | a required attribute or object of §10 absent |
| E3 | an attribute stored with an encoding other than §9.2's, or not valid UTF-8 |
| E4 | a dataset with a dtype §11.1 does not allow; a string dataset not valid UTF-8 or holding a NUL |
| E5 | a dataset whose dimensions or lengths disagree with §10: the row count, the node or cell count, a table's length, the instance count, or the shape `per` requires; a parameter with a missing value (§3.8) |
| E6 | a mesh `kind` or `per` this version does not define; `per = group:<k>` naming anything but a group label; a cell type code not in §15 |
| E7 | units absent where §3.7 requires them, or not parsing by §13 |
| E8 | a name that is not legal, takes a reserved name or prefix (§9.3), or is used twice in the file (§4.4) |
| E9 | a label or mesh-label code outside its table; a `category` naming no table; a category table with a repeated entry |
| E10 | cell arrays inconsistent (§10.2): offsets, node counts by type, or a node number outside the mesh or the cell's instance |
| E11 | a `support_id` that does not match §14 |
| E12 | a relation incomplete or inconsistent: `of` naming nothing, a label or a relation; `quantile` without `q` in (0, 1); `std` or `quantile` units unequal to those of `of`; `with_respect_to` naming neither a parameter nor `coordinates`; `coordinates` without `axis`; both `statistic` and `with_respect_to`; `q` without `statistic = quantile`; a location unlike that of `of` (a derivative with respect to node position excepted) |
| E13 | a vector inconsistent: two fields with one `vector` and `axis`; one vector across locations or units; `axis` without `vector` on a field that is not a derivative; an axis the coordinates do not have |
| E14 | repeated row ids |
| E15 | `generalisation_group` or `run_group` naming anything but a group label; `run_group` on a parameter whose role is not `time`; two `status` labels |
| E16 | a data file with a result naming a `model`, or with `/models`; coordinates naming a `model` or `output` outside a model file whose mesh is per run; a model file with rows, a result without `model`, no model, or a parameter without bounds; in any file, bounds that are not finite or have `lower` > `upper`, or bounds on a label |
| E17 | a result or computed coordinates naming a model that does not exist, or without `output`; a model without `type` or `inputs`; an `inputs` entry naming anything but a parameter, a label or `coordinates`; a `nearest` model breaking §7.5 (columns, bounds, no points) |
| E18 | model data that §12 cannot represent, or whose top level uses `type`, `inputs` or `repr` |
| E19 | an axis of a dataset that is not itself a scale with no dimension scale, more than one, or one not named as §10 gives; a scale without attribute creation order tracked and indexed; a scale whose extent differs from an axis attached to it; an unlimited dimension §10 does not let grow (a zero-extent axis inside model data excepted, §12) |
| E20 | a dataset with a growable dimension that is not chunked; a filter other than gzip 1–9 and shuffle; a user-defined fill value or a `_FillValue` attribute |
| E21 | instances inconsistent: `row_instance` naming an instance that does not exist, giving two rows of one category different instances, or not numbering instances by first appearance; changing-mesh offsets not starting at 0, decreasing, or not ending at the node or cell count; row starts disagreeing with the instance sizes and row order |
| E22 | a soft or external link in the public tree |
| E23 | an object the reader cannot read, deeper than its cap, or (eager read only) above its element limit |
| E24 | coordinates with other than one to three axes |

**Warnings**

| Rule | Finding |
|---|---|
| W1 | a published split that places rows of one generalisation group, or of one run, on both sides |
| W2 | rows whose status is not `converged`, by row |
| W3 | NaN or infinite values in a result, by row and name |
| W4 | a parameter value outside its bounds (and, on evaluation, an input outside a model's domain) |
| W5 | something this version does not define (an attribute, group, role or statistic word), reported and ignored, or read as a plain object (§17) |
| W6 | a chunk larger than §11.4's default |
| W7 | a fixed-length string dataset wider than its longest element |
| W8 | `created` not an ISO 8601 UTC timestamp |
| W9 | two rows of one run at the same time (decidable with `run_group`) |
| W10 | a negative `std` |
| W11 | an array whose values were not checked because it holds more than 2²⁶ (67,108,864) values, the reference validator's limit |

## 17. Versions and additions

`format` reads `gamut/1`. A reader refuses another major version, naming
it. Within version 1, additions are additive: a reader that meets an
attribute, group, role or statistic word it does not know reports W5 and
goes on, ignoring the object. A result with an unknown `statistic` is read
as a plain result, because what it describes is still a value with units;
an object with an unknown role is ignored, because a future role is as
likely an output as an input. A change that makes an existing file mean something else is
version 2.

## 18. Additions planned within version 1

These would be additive under §17, so files written today stay valid:

1. **Tensors.** `axis` takes `x`, `y`, `z`; a symmetric or full tensor
   declaration (`xx`, `xy` …) may follow.
2. **Fields as model inputs.** Model inputs are parameters, labels and
   `coordinates`; a field as an input may follow.

---

## Appendix A. A ParaView view (informative)

ParaView reads VTKHDF natively and ignores groups outside `/VTKHDF`. A
tool can write a VTKHDF UnstructuredGrid, inside the file or beside it,
with one step per row (a run's rows in time order when a time parameter
names a run group): points, connectivity, offsets and types from `/mesh`;
VTKHDF lets step offsets repeat, so a fixed mesh is written once; point and
cell data from the fields, with each declared vector written as one
three-component array; field data from the parameters and scalars. A
changing mesh maps onto VTKHDF's per-step offsets directly.


## Appendix B. Why the format is shaped this way (informative)

Each of these is the simpler of the choices considered.

1. **Row ids live in the `row` coordinate variable** (int64), so the row
   index that generic tools show is the id, and no separate id object
   exists.
2. **Names are unique in a file**, so every call takes a bare name.
3. **Fields are floating point only.** A per-run integer classification is
   stored as floats; mesh labels, fixed in a shared mesh, are the integer
   arrays.
4. **`file_id`, `trained_on` and `evaluated_from`** give model files and
   evaluated files a traceable link to their data without embedding it.
5. **A served result is a zero-length dataset** naming `model` and
   `output`, so a model file is a data file with no rows, plus models.
6. **Model inputs are parameters, labels and `coordinates`**; `nearest`
   takes parameters only, with an exact evaluation order, so every
   implementation gives the same answers.
7. **Instances are numbered by first appearance**, and `row_instance` maps
   rows to them when `per` names a group.
8. **A changing mesh stores instances and fields end to end** with offsets,
   as VTKHDF does, rather than one group per instance.
9. **Vector axes are named `x`, `y`, `z`** by coordinate position.
10. **Unknown roles are ignored with a warning; unknown statistic words are
    read as plain results**: a future role is as likely an output as an
    input, while a statistic still describes a value with units.
11. **A model's `call` receives the outputs wanted**, so a model computes a
    standard deviation or derivatives only when asked.
12. **The CF `coordinates` attribute is written but not required.**
13. **Constants may be int64** as well as floating point.
14. **Persistent free-space management and a 512-entry cap on leading
    chunks**, so a file appended one run at a time, even reopened each
    time, stays the size of its data (measured: 20 columns and 3,000
    single-row appends, each reopening the file, give 0.49 MB, against
    32 MB without).

Design notes
============

Why the model is shaped the way it is, recorded on 2026-09-19 from the
design conversation, so the reasoning survives the people who had it.

The alternatives below retain that design context, not a current survey or
conversion qualification. [SPEC.md](../SPEC.md) and the corpus govern the
current contract; [comparison.md](comparison.md) links current external
references. Clarifications below follow the existing specification.


Long format with roles, not a table per kind of data
----------------------------------------------------

Every observation is a row; the key columns say where in the sampled
space the row sits. A static parametric family, a transient run, a
family of transients, and a sweep of operating points on one geometry
are the same file with different columns populated. The cost is that
semantics no longer come from structure (Exodus has one index, time,
on one mesh, so it never needed to say what the index meant). Roles
with cardinality rules restore the semantics and make the validator a
table rather than a program.

Time is not special: it is a key with role `time`, cardinality one,
and a monotonic check inside its trajectory group. What is special is
the role table itself.


The unit of generalisation is data, not a habit
-----------------------------------------------

The most damaging silent bug in surrogate work is a train/test split
that puts time steps of one run, or variants of one geometry, on both
sides: the model is scored on interpolation inside a case it has
already seen. Most tools have a grouping option; nothing makes a
caller use it. The file now declares which group is the unit of
generalisation, and a split that ignores it is a validator warning
that a tool built on the format can turn into a refusal.


"Varies along" instead of special cases
---------------------------------------

Node coordinates are not special. They are an array with role
`coordinates` that varies along nothing (fixed mesh), a group
(parametric family: one geometry per member, shared by every time
step and condition of that member), or the row (moving mesh). Regions
are not special either: they are integer label arrays, with an optional
category table, one column per taxonomy (CAD face, topology group, material).
The only structures with fixed shape are cells (connectivity) and the
row axis.


No blocks
---------

Exodus blocks solve ragged connectivity for mixed cell types and give
regions a name. VTK's types-offsets-connectivity triple solves the
first in one structure; label arrays solve the second. Blocks would
add a third way to say "these cells belong together".


Connectivity never varies
-------------------------

An aligned producer establishes that node k in every row has the same
meaning. One support states the shared connectivity structurally, and
the validator checks that structure; a content hash gives each support
an identity so its structure can be checked cheaply across files. The
hash excludes changing mesh coordinates and cannot prove semantic node
correspondence between unrelated producers. Rows with different
connectivity are on different supports. The file allows several
supports so it can hold benchmark data with varying meshes; the
alignment claim is then false and the tools say so.


Slots hold data or callables; the callable protocol is four things
--------------------------------------------------------------------

Data is arrays; a surrogate is the same schema with callables filling
slots instead of stored arrays; distillation is evaluating the
callables back into stored arrays. A callable is only `call` (keys
in, values out), `to_dict`, `from_dict`, and an optional `repr`;
everything else it knows is inside its own dictionary. The boundary
is kept that narrow on purpose, so that future models, including
other people's, integrate by conforming to four things and not to a
model of what a surrogate is. Consequences the suite gets for
free:

  - Composition of per-quantity models (x, y, z, pressure, shear) is
    a file whose slots reference several callables sharing a support,
    not a container class inside any one modelling tool, so a tool's
    own record-keeping is never touched.
  - Post-processing is written once against the dataset protocol and
    runs on solver output and predictions alike.
  - Validation is a comparison of two files, per field, per region,
    per row.
  - Provenance, lineage, and validation records are the callable's,
    not the file's: that is the line between the open format and the
    commercial tools, and the format does not cross it.

Bounds are attributes of the key columns. A file with callable slots
may have zero rows or combine rows, stored values and callables; each
slot's `source` decides its content. Bounds declare a domain rather than
certifying accuracy throughout it, and extrapolation warnings are generic
rather than a library special case.


Uncertainty is optional, and a draw is a whole field
-----------------------------------------------------

Whether a producer represents uncertainty at all is its own decision.
The format holds it when asked and is complete without it; a file
that carries none is an ordinary file.

What the format does fix is the shape. A draw is one whole field or
one whole scalar under the `draw` dimension, not a number per node,
so whatever dependence the producer has across nodes is preserved in
the file rather than collapsed into something that cannot be put
back. Summaries follow from the draws by an open routine, and any
summary the format does not name is a derived array with a recipe.
The parameters that change the numbers (draw count, seed, batch size)
belong in the producer's records; the public format does not require them.

A callable's contract is one record per output and nothing more: a
mean and, when the model has one, a band with its level and its
method. The format never needs to know how the band was made, and a
tool that shows a stored mean with its band shows a callable's the
same way. Draws, standard deviations and quantiles are stored data
about stored data; a callable serves none of them.


The public/private boundary
---------------------------

Everything a reader needs to use the data is public and readable
without any proprietary dependency. A callable's dictionary holds its
fitted state; readers that do not own the type preserve supported opaque
content without interpreting or executing it. An optional private group
holds the producer's own records. Neither boundary encrypts the bytes.
This is what lets the format be open while the tools that produce
callables stay closed, and it makes "what does an open user get from
a distilled model" a structural fact: the table, not the object.


HDF5, laid out to also be netCDF-4
----------------------------------

netCDF-4 is HDF5 with a constrained layout: named dimensions as
dimension scales, plain attributes, groups. Staying inside that subset
constrains public values (with dimension-scale machinery exceptions under
SPEC13) and buys named
dimensions in every language (xarray, MATLAB's ncread, Julia's
NCDatasets, R's ncdf4), which is what makes "permute by name" work
without each reader inventing it. The transpose confusion between
MATLAB and Python is a naming problem, and named dimensions dissolve
it. The CF and UGRID vocabularies are not adopted; `units` and
`long_name` are borrowed because they are sensible.


Conformance by corpus
---------------------

A pattern that has worked for us before: the spec plus golden files
with expected values define conformance; every implementation in
every language runs the corpus; no implementation is the reference.
The corpus is what makes a MATLAB writer and a C++ reader agree
without either reading the other's code.


Alternatives considered
-----------------------

PLAID (Safran; CGNS-based; scalars, fields, meshes, splits). Closest
prior art and one we have used ourselves. Not adopted because
its per-sample tree layout is poor for slicing one field across all
samples, it has no first-class time trajectories or family
correspondence, and the CGNS toolchain is heavy in C++. A lossless
export to PLAID should be possible and is worth keeping in mind.

CGNS directly. Aerospace standard with zones, solutions, iterative
data. Same weight problem; its "family" concept is about boundary
conditions, not parametric correspondence.

VTK plus PVD. Fine for a single time series; carries no semantics and
no notion of rows.

Exodus. The direct ancestor of this design: global, nodal, and
element variables over an index; node and side sets; QA records.
Generalised here by replacing the time index with role-tagged keys
and replacing blocks with labels.

The Well and PDEBench. HDF5 conventions for time-dependent physics
built for machine learning; useful precedent for the draw and time
handling, no support for supports or provenance.

netCDF-4 with CF and UGRID wholesale. Rejected as vocabulary, adopted
as layout discipline.

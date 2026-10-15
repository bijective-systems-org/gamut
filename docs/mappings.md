Five datasets mapped onto the model, on paper
==============================================

The test the model must pass before any code exists: every dataset the
suite already handles maps onto the spec with no special case. Where a
mapping needed a special case, that is where the model was wrong. As
of this draft, none did; the places that were close are marked.

These are design mappings, including proposed cases, not new qualification
of a dataset, exporter or modelling workflow. Counts describe the source
snapshots used in this design exercise. The [specification](../SPEC.md) and
corpus govern the current contract; producer correspondence and model
fitness remain separate from structural validation.

Shorthand: keys are written name:role; arrays as name (varies, units,
location, components).


1. TopoLink sphere-cone family (parametric, static, aligned)
------------------------------------------------------------

Source. A TopoLink family export: 122 STEP variants of one baseline
topology, a parameters CSV, a headless solve producing one mesh per
member with 7,394 nodes and 7,392 cells, and a manifest joined to the
CSV by file name.

Rows        122, one per member.
Keys        total_length:design, half_angle:design, nose_radius:design,
            member:group (unit of generalisation), status:status.
Supports    one, kind mesh, quad cells; support_id from node count and
            connectivity; aligned = true.
Arrays      coordinates (row, m, node, 3): each member's own geometry.
            cad_face_id (none, label, node), topo_face_id (none,
            label, cell), topo_group (none, label, cell): the topology
            is shared, so these do not vary.
            cad_edge_t (none, 1, node): the edge parameter for edge
            nodes, dimensionless.
Scalars     none from TopoLink itself.
Notes       optionally the TopoLink version and solver iterations;
            lineage stays with the tools, not the file.
Validator   checks support_id against stored structure. The producer
            establishes correspondence before putting members on that
            shared support; a valid hash cannot detect semantic remapping.

With a solver sweep on top (a freestream sweep per member), rows
become 122 times n_conditions,
keys gain mach:condition and altitude:condition, coordinates become
`varies = group:member`, and pressure (row, field, node, 1, Pa) and
heat_flux (row, field, node, 1, W/m^2) are added.

Close call. Per-node CAD provenance is a label array whose categories
are CAD face ids, which are integers already; the category table is
the identity. Allowed, and it keeps one mechanism.


2. VKI-LS59 turbine cascade (non-parametrised geometry, multi-field)
--------------------------------------------------------------------

Source. 839 RANS solutions on a constant-connectivity mesh of 36,421
nodes; two input scalars; per-sample node coordinates; six fields; six
output scalars; an official split with withheld test outputs.

Rows        839.
Keys        angle_in:condition, mach_out:condition, split:split,
            case:group (unit of generalisation; every row is its own
            geometry).
Supports    one, kind mesh; connectivity identical across samples,
            so aligned = true even though geometry varies.
Arrays      coordinates (row, m, node, 2).
            mach, nut, and four more (row, field, node, 1, each with
            its own units).
Scalars     Q, power, Pr, Tr, eth_is, angle_out, with units.
Status      test rows have withheld outputs: status = partial, with
            NaN in the outputs. The validator warns on non-finite
            values in exactly those rows, which is the right
            behaviour.
Notes       the upstream dataset identifier and licence.

What this buys. Geometry-as-input is a recipe on top (an SVD of the
coordinate ensemble), not a format feature, and the file says the
ensemble is aligned. The producer must establish correspondence before
using that recipe. Six separate fields with units support structural
checks and field-specific analysis; they do not automate model-quality
validation.

Close call. "Aligned" here is a property of the upstream dataset's
construction, not of any tool of ours. Its structure is checkable through
support_id; physical correspondence remains an upstream responsibility.


3. HiLift (scalars only, no support)
------------------------------------

Source. 180 geometries times 10 incidences, bundled CSVs, lift and
drag coefficients.

Rows        1,800.
Keys        the geometry parameters:design, incidence:condition,
            geometry:group (unit of generalisation).
Supports    none.
Arrays      none.
Scalars     CL, CD, CM, dimensionless (units "1").
Validator   warns on a split that puts one geometry on both sides;
            it does not test generalisation to unseen geometries. The
            score's change depends on the data and model.

This is the "not everything is a field" case, and it needs nothing
special: a file with keys and scalars is a complete, valid file.


4. Synthetic transient (time inside a parametric family)
--------------------------------------------------------

Source. To be built for transient work: a heat or Burgers
problem on a fixed 1-D or 2-D mesh, n_runs parameter sets, n_steps
time steps each, possibly with adaptive time stepping.

Rows        n_runs times n_steps (per run; runs may differ in length).
Keys        diffusivity:design, amplitude:design, t:time (units s,
            trajectory_group = run), run:group (unit of
            generalisation).
Supports    one, kind mesh, fixed; coordinates (none, m, node, d).
Arrays      u (row, field, node, 1, K or m/s).
Validator   errors if t is not strictly increasing within a run;
            warns on a split by row instead of by run.

Views a modelling tool can request from this one file: rows as samples
with t as an input column; or trajectories as samples for a
space-time basis; or, later, a dynamics model. The file does not
change between them, which was the point.

Close call. Irregular time steps make the row count per run differ;
long format handles that with no padding. A per-run time grid is a
derived convenience, not a stored structure.


5. Sonic boom ground signature (one-dimensional field, not on a mesh)
---------------------------------------------------------------------

Source. An application case: a parametric area distribution,
flight conditions, a ground overpressure signature over time, and
perceived loudness.

Rows        n_designs times n_conditions.
Keys        area distribution parameters:design, mach:condition,
            altitude:condition, design:group (unit of generalisation).
Supports    one, kind axis: the ground time axis, n_nodes samples,
            coordinates (none, 1, node, 1, s).
Arrays      overpressure (row, field, node, 1, Pa).
Scalars     loudness (PLdB), dimensionless or dB as decided.

What this buys. A modelling tool treats a width-N output the same whether
it is nodes or time samples; the difference is entirely in naming,
plotting, and cards. With an axis support the plot is a line over
time with the right unit, and the card says "overpressure versus
ground time", not "node 412". That is the whole of the "fields not on
a mesh" problem.

Note. This is a field over time that is not a trajectory: time is the
support's coordinate, not a key. The distinction is: a key is
something you sampled; a support coordinate is something every row
reports over. Both are valid, and the roles keep them apart.


6. A model's output (callable slots; composition)
-------------------------------------------------

Not a dataset in the tree, but the case the design was built for.

A zero-row representation of a model trained on dataset 1 with the
freestream sweep has key columns carrying roles and bounds (the training
range, or wider if the modeller says so); support S is stored with the
same support_id as the training file; the slots pressure, heat_flux
(node arrays on S) and CL (scalar) carry their attributes and
`source = callable:m1`; `/callables/m1` holds the callable's
dictionary under its `type`. Evaluating the file on a keys table gives
a file with the same slots holding data, including pressure with its
band beside it (statistic = band, `of` pressure), whose level and
method the callable stated; how the callable arrived at the band was
its own business. A callable file may also retain observations or mix
stored and callable slots (SPEC22).

Five callables, one each for x, y, z, pressure, and shear, sharing
support S and overlapping key bounds, are five slots referencing five
callable ids in one file. The validator checks the declared file
structure, including support_id against stored structure, and reports
key values outside declared bounds. It does not establish correspondence
between independent model producers or compute a model-validity domain
from an intersection of callable bounds. Nothing about the callables'
own records is touched.

Distillation is evaluating the file on a grid of keys and writing the
result with every slot as stored data. The table is public; the
callable that made it is opaque to readers that do not own its type,
which is a schema boundary rather than a confidentiality guarantee.

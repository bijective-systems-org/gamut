# Meshes and fields

A study's results are scalars, one number per run, and fields, one number
per node or per cell of a mesh in every run. A file has one of three
types, read from what it holds and never declared:

| Type | The file has | What it allows |
|---|---|---|
| table | no mesh | the run table |
| shared mesh | one mesh that every run uses; without cells, a point cloud | everything a table allows, plus reads of one node or region across every run, a whole field as one array, comparisons node by node |
| changing mesh | a mesh per run, or per group of runs | one run's fields and the run table |

## The shared mesh

When every run uses the same mesh, node k is the same point in every run.
The mesh is stored once, and each field is one array of runs × nodes (or
runs × cells). Reading one run is a row of it, one region of every run a
set of columns, and one node across every run a single column; each is
one read, and a read decompresses only the stored chunks that hold what
it asks for.

```console
$ gamut info cylinder.gamut
cylinder.gamut: shared mesh, 9 runs
  mesh        576 nodes, 528 cells, fixed
  parameters  gamma [m2 s-1] 0 to 4
  fields      cp [1] at nodes
  zones       surface: field, wall
  file        ... KB
```

The connectivity and the mesh labels never change in a shared mesh. The
coordinates may, stored as often as they change, which the mesh declares
as `per`:

| `per` | The coordinates | For |
|---|---|---|
| `fixed` | one geometry for every run | a sweep of conditions on one mesh |
| `group:<label>` | one geometry per member of a group label | a family of shapes meshed with one topology, each run at several conditions |
| `run` | one geometry per run | a mesh that deforms with every run |

That node k is the same point in every run is the producer's claim: a
solver run on one mesh, a fixed-topology mesher, or a morphing tool such
as TopoLink establishes it. The file records it structurally, by storing
the node count and connectivity once, and identifies the mesh by a digest
of them, its `support_id`, so a model and the study it predicts, or two
studies combined, can be checked to share a mesh.

## Mesh labels

A mesh label is an integer per node or per cell that describes the mesh:
a zone, a boundary patch, a material, a CAD face. Like a run label it can
name a table of names, `field` and `wall` for the cylinder above, and
reads take those names. A boundary condition is a cell label on boundary
faces, with its values as parameters or as fields on those faces.

## Fields

A field lives at the nodes or at the cells, as it was declared, and has
one component. A vector is one field per component, and the components
say they belong together: `u`, `v` with `vector = velocity` and `axis`
`x`, `y`. Tools use that to draw arrows and compute magnitudes. A field
stores its values at the precision it was given, float32 or float64.

## The changing mesh

When the mesh differs from run to run, each run, or each member of a
group, has its own mesh, an *instance* with its own nodes, cells and mesh
labels. Instances and fields are stored end to end, with offsets saying
where each begins, as VTKHDF stores meshes that change from step to
step. Nothing claims that node k of one instance relates to node k of
another, so operations that need it are refused on a changing mesh, with
a message that says so. Turning such a study into a shared-mesh one needs
a correspondence between the meshes, which a mapping or morphing tool
produces.

## Time

A transient run is several rows, one per saved time. Time is a parameter
with the role `time`, and a group label names the run each row belongs
to, so a viewer can animate one run and a trainer can hold out whole
runs. Runs may differ in length and in when they save.

## Uncertainty and derivatives

A result may describe another result, named in its `of`: a standard
deviation, a quantile at a stated probability, or a derivative with
respect to a parameter or to node position (an adjoint sensitivity).
Tools find these by the declaration rather than by name: a viewer draws
error bars from a standard deviation, and a surrogate takes derivatives
as extra training data.

[Example 2](../guide/02-one-mesh.md) writes the cylinder above;
examples [3](../guide/03-geometry-families.md) to
[6](../guide/06-uncertainty-and-gradients.md) cover families, changing
meshes, time and uncertainty.

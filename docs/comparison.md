# How Gamut compares

Gamut holds a parametric study, meaning many runs of one simulation over
its inputs, and the models fitted to it. Most of the formats below were
built for something else and remain the right choice for it. This page
says what each is for, when to keep it, and how a study moves between it
and Gamut.

Gamut is built on HDF5, with a layout that is valid netCDF-4. Those are
its storage foundations. The comparison with another simulation format is
about the data model and the operations it offers; a custom HDF5 layout
is a storage baseline, not another simulation standard.

## Beside each format

| Format | Built for | Keep it when | With Gamut |
|---|---|---|---|
| VTK files (`.vtu`, `.vtp`, [VTKHDF](https://docs.vtk.org/en/latest/vtk_file_formats/vtkhdf_file_format/vtkhdf_specifications.html)) | one mesh and its data, for visualisation; VTKHDF adds time steps | you are looking at results in ParaView or VisIt | `gamut-vtk` turns a folder of runs into one study, and a study back into a folder ([VTK](guide/10-vtk.md)); cells use VTK's codes and node order |
| [CGNS](https://cgns.org/) | CFD solutions: zones, boundary conditions, solver state | a solver reads or restarts from it | write each run's results from the solver, or convert its output; zones and patches become mesh labels |
| [Exodus II](https://sandialabs.github.io/seacas-docs/html/index.html) | finite-element meshes, blocks, sets and results through time, built on netCDF | your finite-element tools need its model and ecosystem | retain native results; collect runs, their design/condition inputs and their study relationships in Gamut |
| [PhysicsNeMo-Mesh (`.pmsh`)](https://docs.nvidia.com/physicsnemo/latest/user-guide/mesh/using_mesh.html#serialization) | simplicial meshes with tensor fields, stored as memory-mapped tensors for PhysicsNeMo/PyTorch workflows | mesh processing and training happen in that ecosystem | Gamut holds the study and its run relationships; a training pipeline can materialise the arrays or meshes it needs |
| [CAE OpenUSD](https://github.com/NVIDIA-Omniverse/cae-openusd-plugins) | exposing scientific/engineering data through OpenUSD schemas and on-demand readers | your workflow composes or visualises simulation assets through USD | the current plugins retain native files as the source of truth; a Gamut adapter would be a separate integration, not an existing feature |
| netCDF with [CF](https://cfconventions.org/) and [UGRID](https://ugrid-conventions.github.io/ugrid-conventions/) | geoscience data, with conventions for grids, meshes and time | you share with climate and ocean tools | a Gamut file is a netCDF-4 file: netCDF tools and xarray read it as it is; Gamut adds what a study means, such as runs, roles, statuses and relations |
| [Zarr](https://zarr.dev/) | chunked arrays in object storage, read by many workers at once | reads go over the network to a cluster | a Gamut file is one local file; copy it, or extract the part a job needs |
| Parquet or CSV | tables | the study has no fields and the meaning lives elsewhere | the run table carries units, roles and statuses; `gamut get study.gamut mach cl -o table.csv` exports columns |
| Dataset packages for machine learning ([PLAID](https://plaid-lib.readthedocs.io/), [The Well](https://polymathic-ai.org/the_well/)) | benchmark datasets with loaders and fixed splits | the benchmark's loader is what you need | a study keeps its published splits and its unit of generalisation, and a fitted model is a file of the same shape |

The [benchmarks](benchmarks.md) measure size and read speed against
several of these on real studies.

Exodus and CGNS already supply scientific data models and established
language interfaces. Gamut's particular focus is the study across runs:
design and condition parameters, status, published splits, the unit of
generalisation and shared-mesh correspondence. Its Python, MATLAB, Julia,
C++ and C interfaces use that study vocabulary. This is a scope comparison,
not a claim that other formats cannot carry metadata or be read across languages.

## Storage foundations and baselines

HDF5, netCDF-4 and Zarr can store the arrays behind a study. A team choosing
its own layout also chooses how to represent units, inputs, statuses, run
relationships and geometry identity, and maintains the code interpreting
those choices. Gamut publishes those conventions and implements the study
operations. Generic HDF5/netCDF tools can still inspect its public layout.

A custom layout can be faster for a particular access pattern. The
benchmark's matched h5py baseline reads Gamut's actual datasets, with the
same chunks and compression, to make the cost of the interface visible.
The separate group-per-run HDF5 baseline measures that layout; its timings
are not a limit of HDF5.

## What Gamut adds

A study is one file, holding the run table, the mesh and the fields, with
units, roles and statuses written in the file rather than kept in a
script. On a shared mesh, node k is the same point in every run, so a
field is one block of runs × nodes: one run, one region of every run, or
one node across thousands of runs is a single read, and a model can be
trained on the block directly. A validator names the rules a file
breaks, and a corpus of valid, broken and hostile files holds every
implementation to the specification. A fitted model is stored in the same
terms as the data, and evaluating it produces an ordinary study.

## What it does not do

Gamut is not a solver's file. It holds results and the inputs that
produced them, not solver state, so keep the solver's own files for
restarts. A study is one file read locally; there is no object-store or
server access, and a very large study is read a part at a time.

Version 1 leaves out polyhedral cells (export them decomposed), declared
tensors (store their components) and fields as model inputs. The
[specification](../SPEC.md#18-additions-planned-within-version-1) lists
what is planned within version 1. Unit conversion on reads is Python's
alone, through pint; MATLAB, Julia and C return values in the units they
were stored in.

## Moving between them

A conversion maps names, units, roles, statuses and splits explicitly;
nothing about a run's meaning is guessed from the container. When the runs
of a study were meshed separately, a node-by-node comparison needs a
correspondence first, from a mapping or morphing tool; until then they are
a [changing mesh](guide/04-changing-meshes.md), which keeps every run
exactly as it was computed.

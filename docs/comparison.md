# How mestra compares

mestra is for one thing: a parametric study, meaning many runs of one
simulation over its inputs, and the models fitted to it. Most formats it
meets were built for something else, and remain the right choice for it.
This page says what each is for, when to keep it, and how a study moves
between it and mestra.

## Beside each format

| Format | Built for | Keep it when | With mestra |
|---|---|---|---|
| VTK files (`.vtu`, `.vtp`, [VTKHDF](https://docs.vtk.org/en/latest/vtk_file_formats/vtkhdf_file_format/vtkhdf_specifications.html)) | one mesh and its data, for visualisation; VTKHDF adds time steps | you are looking at results in ParaView or VisIt | `mestra-vtk` turns a folder of runs into one study, and a study back into a folder ([VTK](guide/10-vtk.md)); cells use VTK's codes and node order |
| [CGNS](https://cgns.org/) | CFD solutions: zones, boundary conditions, solver state | a solver reads or restarts from it | write each run's results from the solver, or convert its output; zones and patches become mesh labels |
| [Exodus II](https://github.com/sandialabs/seacas) | finite-element models and results for the SEACAS tools | your finite-element tools need it | as for CGNS |
| netCDF with [CF](https://cfconventions.org/) and [UGRID](https://ugrid-conventions.github.io/ugrid-conventions/) | geoscience data, with conventions for grids, meshes and time | you share with climate and ocean tools | a mestra file is a netCDF-4 file: netCDF tools and xarray read it as it is; mestra adds what a study means, such as runs, roles, statuses and relations |
| HDF5 in your own layout (h5py) | any arrays, arranged as one program likes | the file never leaves that program | mestra is HDF5 with a published layout and a validator, so someone else, in another language, reads it without your script |
| [Zarr](https://zarr.dev/) | chunked arrays in object storage, read by many workers at once | reads go over the network to a cluster | a mestra file is one local file; copy it, or extract the part a job needs |
| Parquet or CSV | tables | the study has no fields and the meaning lives elsewhere | the run table carries units, roles and statuses; `mestra get study.mes mach cl -o table.csv` exports columns |
| Dataset packages for machine learning ([PLAID](https://plaid-lib.readthedocs.io/), [The Well](https://polymathic-ai.org/the_well/)) | benchmark datasets with loaders and fixed splits | the benchmark's loader is what you need | a study keeps its published splits and its unit of generalisation, and a fitted model is a file of the same shape |

The [benchmarks](benchmarks.md) measure size and read speed against
several of these on real studies.

## What mestra adds

- **One file per study**, holding the run table, the mesh and the fields,
  with units, roles and statuses written down rather than kept in a script.
- **Correspondence as structure.** On a shared mesh, node k is the same
  point in every run, so a field is one block of runs × nodes and a model
  can be trained on it directly.
- **Reads across runs**: one run, one region of every run, or one node
  across thousands of runs.
- **A validator** that names every rule a file breaks, and a corpus of
  valid, broken and hostile files that every implementation is held to.
- **Models in the same terms as the data**, evaluated into an ordinary
  study.

## What it does not do

- **It is not a solver's file.** It holds results and the inputs that
  produced them, not solver state; keep the solver's own files to restart.
- **It is one file, read locally.** There is no object-store or server
  access; very large studies are read a part at a time.
- **Version 1 leaves out** polyhedral cells (export them decomposed),
  declared tensors (store components), and fields as model inputs. The
  [specification](../SPEC.md#18-additions-planned-within-version-1) lists
  what is planned within version 1.
- **Unit conversion on reads** is in Python only for now.

## Moving between them

A conversion maps names, units, roles, statuses and splits explicitly;
nothing about a run's meaning is guessed from the container. When the runs
of a study were meshed separately, a node-by-node comparison needs a
correspondence first, from a mapping or morphing tool; until then they are
a [changing mesh](guide/04-changing-meshes.md), which keeps every run
exactly as it was computed.

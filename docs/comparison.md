mestra and other formats
========================

This comparison answers where a study file fits beside solver and dataset
formats. It is a reading map, not a conversion guarantee or an exhaustive
capability matrix. External references were checked on 14 October 2026;
implementations and conventions can evolve.

mestra represents observations as rows with role-tagged keys, per-row
scalars, supports and array slots, optionally served by callables. Its
specification and corpus define those meanings. It can hold several
supports; the aligned case has at most one, with correspondence established
by the producer. [Design notes](design-notes.md) retain the original choices.


What the other formats describe
-------------------------------

| Format / project | Relevant documented structure |
|---|---|
| [VTKHDF](https://docs.vtk.org/en/latest/vtk_file_formats/vtkhdf_file_format/vtkhdf_specifications.html) | Point, cell and field data on VTK dataset types, with temporal steps and composite structures. |
| [CGNS](https://cgns.org/standard/FMM/nodes.html) | A CFD data model with zones, solution data and dimensional-unit structures. |
| [Exodus II](https://github.com/sandialabs/seacas) | A finite-element analysis database used by the SEACAS preprocessing, postprocessing and translation tools. |
| [CF](https://cfconventions.org/) and [UGRID](https://ugrid-conventions.github.io/ugrid-conventions/) | Metadata conventions for netCDF variables; UGRID describes unstructured-mesh topology and associated data. |
| [PLAID](https://plaid-lib.readthedocs.io/en/latest/concepts/problem_definition.html) | Physics-simulation datasets with problem definitions selecting input/output features and train/test splits. |
| [The Well](https://polymathic-ai.org/the_well/api/) | Shared HDF5 datasets with loaders and training/validation/test data interfaces. |
| [PDEBench](https://github.com/pdebench/PDEBench) | PDE simulation benchmark data, HDF5 preparation and model/data-loading workflows. |

These positive descriptions do not assert that another format has no place
for roles, units, uncertainty, models or custom metadata. A comparison of
those features needs the specific schema, convention and reader version;
absence from this table is not evidence of absence from a format.


Moving data in and out
----------------------

Keep solver-native files when their zones, boundary conditions, solver state
or established post-processing are needed. A derived mestra file can gather
observations for comparison or modelling. Conversion must explicitly map
keys, roles, units, groups, splits and status, and establish correspondence
before declaring rows aligned. No conversion's losslessness, effort or
performance is established by a shared container or matching cell codes.

- **VTK cells.** mestra uses VTK cell codes and node order (SPEC20). A
  converter still maps attributes and checks the mesh/data it writes.
- **netCDF-4 and xarray.** Generic tools can read the public layout;
  `xarray.open_datatree(path)` exposes groups and named dimensions.
  `Dataset.to_xarray()` is a separate package adapter. Generic rewrites
  need not preserve mestra conformance (SPEC21).
- **PLAID.** A study mapping may associate samples with rows and explicit
  problem-definition splits with a split key. It must supply the mestra
  semantics it needs; the source schema alone does not establish producer
  correspondence or modelling policy. [Design mappings](mappings.md) are
  conceptual examples, not qualified converters.
- **Catalogues.** A card or catalogue may point to the file; catalogue
  display and its metadata need their own integration checks.
- **Models.** A tool could register an additional callable type carrying
  an FMI or ONNX payload. This is a possible extension, not a shipped
  adapter or execution guarantee.

For remote or large-data work, qualify the actual access pattern and
storage environment. mestra's lazy reads and row chunking do not establish
network or object-store performance.


The mestra boundary
-------------------

Stored public data is readable without a proprietary runtime. The built-in
`affine` exercises callable conformance; other types require their owning
software to execute, including any licence it requires. Supported opaque
preservation is not encryption or proof that every unknown object survives
a rewrite. The [compatibility notes](compatibility.md) describe language,
preservation and native-parser limits.

Lineage and validation records belong to the producer, using its records
or private content. Package versions are separate from `mestra/0`; changes
to existing file meaning follow [CONTRIBUTING.md](../CONTRIBUTING.md).

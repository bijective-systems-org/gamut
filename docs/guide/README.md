# Guide

Every study file is made and read the same way, in every language:

1. `create` declares every name the file will hold, with its units and its
   role: inputs (parameters), names such as a status (labels), and results
   (scalars, and fields on a mesh).
2. `add_run` gives each run's values; `open(path, mode="a")` adds runs
   later.
3. `open` reads: `select` picks rows by a condition, such as
   `status == converged`, and a `get_` call reads one name for those rows.
4. `gamut validate` checks a file against the rules of the specification.

Most studies need only the first two pages. The others each add one idea,
for when a study has it. Each page runs one script from
[`examples/`](https://github.com/bijective-systems-org/gamut/tree/main/examples), from a checkout with the Python package
installed ([installing](../install.md)), and shows what it prints.
`gamut info FILE` lists what a file holds, from any shell.

| | Page | For a study with |
|---|---|---|
| 1 | [Run tables](01-run-tables.md) | inputs and results per run, and which runs failed; no mesh |
| 2 | [One mesh](02-one-mesh.md) | every run on one mesh, with fields at its nodes or cells |
| 3 | [Geometry families](03-geometry-families.md) | several shapes meshed with one topology, and a train/test split |
| 4 | [Changing meshes](04-changing-meshes.md) | a different mesh per run |
| 5 | [Time series](05-time-series.md) | transient runs, a row per saved step |
| 6 | [Uncertainty and gradients](06-uncertainty-and-gradients.md) | a spread, quantiles or a derivative beside a result |
| 7 | [Models](07-models.md) | a fitted model to share and evaluate on new inputs |
| 8 | [Reading parts](08-reading-parts.md) | more data than memory, regions, other units |
| 9 | [Combining files](09-combining-files.md) | runs from several files, or a subset of one |
| 10 | [VTK](10-vtk.md) | a folder of VTK files to bring in, or to write back out |

The same files from other places:

| | Page | |
|---|---|---|
| 11 | [Command line](11-command-line.md) | inspect, check, build from a spreadsheet and extract without writing code |
| 12 | [MATLAB](12-matlab.md) | the same calls in MATLAB's spelling, and reading with `ncread` alone |
| 13 | [Julia](13-julia.md) | the same calls, in Julia's spelling |
| 14 | [C++ and C](14-c-and-cpp.md) | the same calls in C++, and the C interface under every language |

## Words used throughout

| Word | Means |
|---|---|
| run | one simulation; a row of the run table (a transient run has a row per saved step) |
| parameter | an input that places a run in the study: a design variable, an operating condition, a time |
| label | a value that names rather than measures: a status, a geometry's name, a solver |
| scalar | a result with one number per run, such as a lift coefficient |
| constant | one number for the whole study, such as a reference area |
| mesh | nodes, and optionally cells, that fields live on |
| field | a result with one number per node, or per cell, in every run |
| mesh label | an integer per node or cell that describes the mesh: a zone, a boundary patch |

The [specification](https://github.com/bijective-systems-org/gamut/blob/main/SPEC.md) defines each of these exactly.

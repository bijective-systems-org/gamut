# Guide

Each page takes one idea, shows the script in [`examples/`](../../examples)
that uses it, and what the script prints. Read the first two pages first;
after that, take the pages in any order.

The scripts run from a checkout with the Python package installed
([installing](../install.md)); each writes its file in the current
folder. `gamut info FILE` lists what a file holds and `gamut validate FILE`
checks it, from any shell.

| | Page | The example writes |
|---|---|---|
| 1 | [Run tables](01-run-tables.md) | a wing's polar: inputs, results and status, with units |
| 2 | [One mesh](02-one-mesh.md) | flow past a cylinder, every run on one mesh |
| 3 | [Geometry families](03-geometry-families.md) | three shapes on one mesh topology, compared node by node |
| 4 | [Changing meshes](04-changing-meshes.md) | a refinement study, a mesh per run |
| 5 | [Time series](05-time-series.md) | two transient runs, a row per saved step |
| 6 | [Uncertainty and gradients](06-uncertainty-and-gradients.md) | a spread, quantiles and a derivative beside a result |
| 7 | [Models](07-models.md) | a fitted model as a file, evaluated on new inputs |
| 8 | [Reading parts](08-reading-parts.md) | runs by condition, nodes by zone, values in other units |
| 9 | [Combining files](09-combining-files.md) | two days of runs as one file, a subset, a rewrite |
| 10 | [VTK](10-vtk.md) | a folder of VTK files as one study, and back |

The same files from other places:

| | Page | |
|---|---|---|
| 11 | [Command line](11-command-line.md) | inspect, check, build and extract without writing code |
| 12 | [MATLAB](12-matlab.md) | the same calls, in MATLAB's spelling |
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

The [specification](../../SPEC.md) defines each of these exactly.

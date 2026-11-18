# Examples

Start with [First file](../first-file.md) to write, read and inspect a
three-run table. Then pick the example that fits your study. Each page
links to a [runnable program](https://github.com/bijective-systems-org/gamut/tree/main/examples)
and shows what it prints.

| | Example | For a study with | Languages |
|---|---|---|---|
| 1 | [Run tables](01-run-tables.md) | inputs and results per run, and which runs failed; no mesh | Python, MATLAB, Julia, C++, Rust |
| 2 | [One mesh](02-one-mesh.md) | every run on one mesh, with fields at its nodes or cells | Python, MATLAB, Julia, C++, Rust |
| 3 | [Geometry families](03-geometry-families.md) | several shapes meshed with one topology, and a train/test split | Python, MATLAB, Julia, C++, Rust |
| 4 | [Changing meshes](04-changing-meshes.md) | a different mesh per run | Python, MATLAB, Julia, C++, Rust |
| 5 | [Time series](05-time-series.md) | transient runs, a row per saved step | Python, MATLAB, Julia, C++, Rust |
| 6 | [Uncertainty and gradients](06-uncertainty-and-gradients.md) | a spread, quantiles or a derivative beside a result | Python, MATLAB, Julia, C++, Rust |
| 7 | [Models](07-models.md) | a fitted model to share and evaluate on new inputs | Python, MATLAB; the built-in model in Julia, C++ and Rust too |
| 8 | [Reading parts](08-reading-parts.md) | more data than memory, regions, other units | Python, MATLAB, Julia, C++, Rust |
| 9 | [Combining files](09-combining-files.md) | runs from several files, or a subset of one | Python, MATLAB, Julia, C++, Rust |
| 10 | [VTK](10-vtk.md) | a folder of VTK files to bring in, or to write back out | Python, command line |

The [reference](../reference/command-line.md) has the command line and
each language's spelling of the same calls; [how it works](../concepts/README.md)
explains what the files hold and why.

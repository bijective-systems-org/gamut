# Examples

Every study file is made and read the same way, in every language:

1. `create` declares every name the file will hold, with its units and its
   role: inputs (parameters), names such as a status (labels), and results
   (scalars, and fields on a mesh).
2. `add_run` gives each run's values; opening the file to append adds runs
   later.
3. `open` reads: `select` picks rows by a condition, such as
   `status == converged`, and a `get_` call reads one name for those rows.
4. `gamut validate` checks a file against the rules of the specification.

The examples build on one another: most studies need only the first two,
and each of the others adds one idea, for when a study has it. Each is a
program in [`examples/`](https://github.com/bijective-systems-org/gamut/tree/main/examples),
shown with what it prints, and the tests run every one. Where an example
is written in more than one language, the programs are the same and print
the same lines; choosing a language shows it in every example.

| | Example | For a study with | Languages |
|---|---|---|---|
| 1 | [Run tables](01-run-tables.md) | inputs and results per run, and which runs failed; no mesh | Python, MATLAB, Julia, C++ |
| 2 | [One mesh](02-one-mesh.md) | every run on one mesh, with fields at its nodes or cells | Python, MATLAB, Julia, C++ |
| 3 | [Geometry families](03-geometry-families.md) | several shapes meshed with one topology, and a train/test split | Python |
| 4 | [Changing meshes](04-changing-meshes.md) | a different mesh per run | Python |
| 5 | [Time series](05-time-series.md) | transient runs, a row per saved step | Python |
| 6 | [Uncertainty and gradients](06-uncertainty-and-gradients.md) | a spread, quantiles or a derivative beside a result | Python |
| 7 | [Models](07-models.md) | a fitted model to share and evaluate on new inputs | Python; evaluated in MATLAB and Julia |
| 8 | [Reading parts](08-reading-parts.md) | more data than memory, regions, other units | Python |
| 9 | [Combining files](09-combining-files.md) | runs from several files, or a subset of one | Python |
| 10 | [VTK](10-vtk.md) | a folder of VTK files to bring in, or to write back out | Python, command line |

The [reference](../reference/command-line.md) has the command line and
each language's spelling of the same calls; [how it works](../concepts/README.md)
explains what the files hold and why.

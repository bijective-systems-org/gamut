# Start here

Gamut stores a simulation study as one file: the runs, what went into
each, what came out, and the mesh the fields live on. This page goes from
installing it to using it on your own studies, and names the page that
covers each step in more depth.

## The first ten minutes

Install the Python package in a Python 3.10 or later environment, and
check that the command line answers:

```bash
pip install gamut-format
gamut --version
```

The version line names the format the package writes, `gamut/1`. Until
version 1 is released on PyPI, install from a checkout instead, with
`pip install .` at its top. [Installing](install.md) covers MATLAB, Julia
and C.

From a checkout of this repository, run the first two examples:

```bash
cd examples
python 01_run_table.py
python 02_one_mesh.py
```

The first writes a wing's polar, a table of runs with inputs, results and
a status, and reads parts of it back by condition. The second writes flow
past a cylinder on one mesh shared by every run, and reads one region and
one node across every run.

Then look inside a file without Python:

```bash
gamut info cylinder.gamut
gamut validate cylinder.gamut
```

`info` lists what the file holds and in which units. `validate` checks it
against the [specification](../SPEC.md) and names any rule it breaks.

## The first day

Read the [guide](guide/README.md) in order. Each page is short and runs
one example. After the first two pages you will write a geometry family,
several shapes on one mesh topology so that fields compare node by node
([families](guide/03-geometry-families.md)); runs on meshes that change
from run to run, as in a refinement study
([changing meshes](guide/04-changing-meshes.md)); transient runs, with a
row per saved step ([time series](guide/05-time-series.md)); a spread and
a derivative stored beside the result they describe
([uncertainty](guide/06-uncertainty-and-gradients.md)); and a model file
evaluated on new inputs ([models](guide/07-models.md)).

## The first week

If your runs are a folder of `.vtu` or `.vtk` files, `gamut-vtk import
runs/` writes two small tables for you to fill in, the inputs of each run
and the units of each array, and then turns the folder into one study
([VTK](guide/10-vtk.md)).

If you write your solver's output yourself, add runs with `add_run` as
they finish. A file can be reopened and appended to as the study grows
([one mesh](guide/02-one-mesh.md),
[combining files](guide/09-combining-files.md)).

Reads take only what they need: runs by condition, nodes by zone, values
in the units you ask for ([reading parts](guide/08-reading-parts.md)).
The [command line](guide/11-command-line.md) builds a file from a JSON
document and extracts columns and fields to CSV or NumPy files, for
scripts that should not link the library.

## The first month

MATLAB and Julia read and write the same files with the same calls
([MATLAB](guide/12-matlab.md), [Julia](guide/13-julia.md)), and C and C++
programs link the core directly ([C and C++](guide/14-c-and-cpp.md)).
A model fitted with other software is stored through a small class with
`load`, `save` and `call`, so its file can be evaluated wherever that
software is installed ([models](guide/07-models.md)).

Before opening files from other people in a long-running program, read
[opening files from outside](security.md): what the readers check, and
the one case where a separate process is the only protection.
[How it compares](comparison.md) sets Gamut beside the formats you
already use and says when to keep them, and the
[benchmarks](benchmarks.md) measure size and read speed on two real
studies.

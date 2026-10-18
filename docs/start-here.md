# Start here

mestra turns a simulation study into one file: the runs, what went into
each, what came out, and the mesh the fields live on. This page is the road
through it, from installing to using it on your own studies. Each step
names the page that goes deeper, and none of them needs more than the
step before.

## The first ten minutes

1. **Install.** `pip install mestra` in a Python 3.10 or later environment
   (other languages: [installing](install.md)). Check it with
   `mestra --version`.
2. **Run the first two examples.** From a checkout of this repository:

   ```bash
   cd examples
   python 01_run_table.py
   python 02_one_mesh.py
   ```

   The first writes a wing's polar, a table of runs with inputs, results
   and a status, and reads parts of it back by condition. The second writes
   flow past a cylinder on one mesh shared by every run, and reads one
   region and one node across every run.
3. **Look inside a file without Python.**

   ```bash
   mestra info cylinder.mes
   mestra validate cylinder.mes
   ```

   `info` says what the file holds and in which units; `validate` checks it
   against the [specification](../SPEC.md) and names any rule it breaks.

You have now seen the whole shape: a run table, a mesh, fields on it, and a
file that explains itself.

## The first day

Read the [guide](guide/README.md) in order; each page is short and runs one
example. By the end of it you will have written:

- a **geometry family**, members with different shapes on one mesh
  topology, so fields compare node by node across the family
  ([families](guide/03-geometry-families.md));
- runs on **meshes that change**, as in a refinement study
  ([changing meshes](guide/04-changing-meshes.md));
- **transient runs**, where every saved step is a row
  ([time series](guide/05-time-series.md));
- **uncertainty and gradients** stored beside the values they describe
  ([uncertainty](guide/06-uncertainty-and-gradients.md));
- a **model file** and its evaluation on new inputs
  ([models](guide/07-models.md)).

## The first week: your own studies

- **From VTK files.** If your runs are a folder of `.vtu` or `.vtk` files,
  `mestra-vtk import runs/` writes the two small tables it needs (the inputs
  of each run, the units of each array) and, once they are filled in,
  turns the folder into one study ([VTK](guide/10-vtk.md)).
- **From your solver's own output.** Write runs as they finish with
  `add_run`, one at a time; a file can be reopened and appended to as the
  study grows ([one mesh](guide/02-one-mesh.md),
  [combining files](guide/09-combining-files.md)).
- **Reading only what you need.** Choose runs by condition, nodes by zone,
  and units on the way out ([reading parts](guide/08-reading-parts.md)).
- **From other tools.** The [command line](guide/11-command-line.md) builds
  a file from a JSON document and extracts columns and fields to CSV or
  NumPy files, for scripts and agents that should not link the library.

## The first month

- **MATLAB and Julia** read and write the same files with the same calls
  ([MATLAB](guide/12-matlab.md), [Julia](guide/13-julia.md)); C and C++
  programs link the core directly ([C and C++](guide/14-c-and-cpp.md)).
- **Models fitted elsewhere** plug in with a small class (load, call, save),
  so a model file evaluates wherever its software is installed
  ([models](guide/07-models.md)).
- **Files from outside.** Opening a file from someone else is safe: sizes
  are checked before memory is used, and links are never followed
  ([security](security.md)).
- **How it compares** with the formats you already use, and when to keep
  them ([comparison](comparison.md)); what it costs and saves on real
  studies ([benchmarks](benchmarks.md)).

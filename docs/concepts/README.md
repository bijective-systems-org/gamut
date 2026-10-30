# How it works

A Gamut file holds one parametric study, the runs of a simulation over
its inputs, or one model fitted to such a study. It says what every
number in it is: its name, its units, its role and where it lives, so a
reader needs nothing but the file. These pages explain what a file holds
and how it is stored; the
[specification](https://github.com/bijective-systems-org/gamut/blob/main/SPEC.md)
defines it exactly, rule by rule.

## The run table

Every file is a table with a row per run. A run is located by its
**parameters**, numbers with units and a role: `design` for the shape of
the thing, `condition` for how it is operated, `time` for a saved step.
**Labels** name rather than measure: a status, a solver, the member of a
family; they are stored as a code per row with a table of names.
**Scalars** are results with one value per run, and **constants** hold
one value for the whole study, such as a reference area.

```console
$ gamut info polar.gamut
polar.gamut: table, 18 runs
  parameters  alpha [degree] -2 to 8, mach [1] 0.6 to 0.8
  labels      status (status): 17 converged, 1 failed
  results     cd [1], cl [1]
  constants   reference_area = 12.5 m2
  file        ... KB
```

That is the file of [the first example](../guide/01-run-tables.md). Every
row gets an id when it is written, unique in the file and never reused,
so a run can be traced after it is copied to another file. Units are
required on every number. A result a run does not have, as for the
failed run here, is NaN; parameters and labels are never missing.

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

## Beyond the table

A study with fields adds a mesh. When every run uses the same mesh, node
k is the same point in every run, and a field is stored as one block of
runs × nodes ([meshes and fields](meshes.md)). A **model file** holds no
runs: it holds models fitted to a study and the inputs and results they
serve, and evaluating it gives an ordinary study ([models](models.md)).

## Why it is shaped this way

**One file per study.** The runs, their inputs, their results, the mesh
and what each number means travel together, so a study can be sent,
archived or cited as one thing.

**Declared, not guessed.** A file is created with every name declared up
front, with its units and its role, and nothing is inferred later from
the values. Names are unique in a file, so every call takes a bare name.

**A field on a shared mesh is one array.** Runs that share a mesh store
it once, and each field as runs × nodes, so one run, one region of every
run, or one node across thousands of runs is a single read, and a model
trains on the array as it is.

**Other tools read it.** The file is HDF5 laid out as netCDF-4, so h5py,
xarray, the netCDF tools and MATLAB's `ncread` read it without this
package ([the file underneath](the-file.md)).

**Models are data.** A model file stores a model's numbers, never code.
The software that owns a model's type runs it; the built-in nearest-run
model runs in every language.

**Checked when written.** Every rule is numbered. A writer refuses input
that would break one, naming the rule, and `gamut validate` reports every
rule a file breaks ([rules and validation](validation.md)).

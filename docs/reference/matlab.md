# MATLAB

MATLAB reads and writes the same files with the same calls, in MATLAB's
spelling: methods on a study object in camelCase, options as name–value
pairs, declarations as structs, and positions counted from 1. The toolbox,
`Gamut.mltbx`, installs it with no compiler ([installing](../install.md#matlab)).
Every example in the [examples](../guide/README.md) has a MATLAB tab.

## The same calls

| Python | MATLAB |
|---|---|
| `gamut.create(path, writer=w, fields={...})` | `gamut.create(path, 'writer', w, 'fields', struct(...))` |
| `study.add_run(values, fields=...)` | `study.addRun(values, 'fields', ...)` |
| `study.add_runs(pandas.read_csv(path))` | `study.addRuns(readtable(path))`, or a struct of columns |
| `study.get_field("p", rows=r, nodes=n)` | `study.getField('p', 'rows', r, 'nodes', n)` |
| `study.select("mach > 0.7")` | `study.select('mach > 0.7')`, positions from 1 |
| `study.outside("alpha", rows=r)` | `study.outside('alpha', 'rows', r)` |
| `study.row_count` | `study.rowCount()` |
| `study.table()` | `study.table()`: a MATLAB `table`, labels as `categorical` |
| `gamut.register_model_type(cls)` | `gamut.registerModelType(className)` |
| `study.model_numbers("fit")` | `study.modelNumbers('fit')`: a struct |
| `gamut.append`, `extract`, `write_copy`, `validate` | `gamut.append`, `extract`, `writeCopy`, `validate` |

`help gamut.Study` describes the study object, and `methods(study)` lists
what it can do.

## Conventions

Declarations are structs, one field per name: `struct('cl', '1')` for a
scalar in units of 1, `struct('alpha', struct('units', 'degree', 'role',
'condition'))` for a parameter. `select` returns positions counted from 1,
and every read takes them as `'rows'`: left out, or `':'`, is every row,
and `[]` is none, so the rows of a `select` that matched nothing read
nothing. Cells are a cell array `{types, offsets, connectivity}` in VTK's
convention, as in every language, so the node numbers inside
`connectivity` count from 0. The stored codes of a label or mesh label
also count from 0 in every language: a zone's code is its place in
`categories` minus one. A refusal is an error whose identifier names the
rule, such as `gamut:E16`.

## Reading without the package

A study file is netCDF-4, so MATLAB's own `ncread` reads it with nothing
installed; a colleague who only reads can skip the package.

```matlab
f = 'sweep.gamut';
cl = ncread(f, 'cl');                                % one value per run
names = ncread(f, '/categories/status');             % the status names
status = names(ncread(f, 'status') + 1);             % each run's status
converged = status == "converged";
```

A label comes as its codes, counted from 0; its names are the table under
`/categories` that its `category` attribute names. Values come in the
units they were stored in (`ncreadatt(f, 'cl', 'units')`). A field on a
shared mesh is `/mesh/node_fields/<name>` (or `cell_fields`), which
`ncread` gives as nodes × runs, the axes reversed as for every netCDF
array MATLAB reads. `ncinfo(f)` lists everything in a file. Writing,
selecting by condition, models and validation need the package
([`examples/matlab/read_with_ncread.m`](https://github.com/bijective-systems-org/gamut/blob/main/examples/matlab/read_with_ncread.m)
is the whole program).

## Inputs outside a model's range

`gamut.evaluate` evaluates a [model file](../guide/07-models.md) and returns its
answer, a study open to read. An input outside the range the model was
fitted on is evaluated with a warning (`gamut:W4`), and the answer keeps
the model's bounds, so it can say which rows lie outside and how far.
[`evaluate_model.m`](https://github.com/bijective-systems-org/gamut/blob/main/examples/matlab/evaluate_model.m) asks the
models page's quadratic about 5 and 12 degrees:

```matlab
answer = gamut.evaluate('lift_model.gamut', struct('alpha', [5; 12]));
outside = answer.outside('alpha');
answer.close();
```

```text
degrees outside the fitted range: 0 2
```

`outside` gives a number per row in the parameter's units: 0 inside the
bounds or on one, negative below them, positive above.

## Notes

- A file written by MATLAB is the same file Python, Julia and C read: the
  library underneath is one and the same.
- MATLAB loads its own HDF5. The toolbox's library carries its own HDF5
  linked in, so the two never meet; a gateway built from a checkout needs
  such a core too ([installing](../install.md#compiling-the-gateway)).
- Values arrive in the units they were stored in, which
  `study.describe(name).units` names. Converting them is left to the
  caller; only Python's reads convert, through pint.
- Keep names, table entries and labels to ASCII if MATLAB will read the
  file; the format allows any UTF-8.

Next: [Julia](julia.md).

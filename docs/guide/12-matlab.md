# 12. MATLAB

MATLAB reads and writes the same files with the same calls, in MATLAB's
spelling: methods on a study object in camelCase, options as name–value
pairs, declarations as structs, and positions counted from 1. The toolbox, `Gamut.mltbx`, installs it with
no compiler ([installing](../install.md#matlab)).

There are two examples, from a working folder with `examples/matlab` on
the path: `sweep`, the [README](../../README.md#example)'s run table, and
`one_mesh`, eight runs of flow past a cylinder on one mesh, with a ninth
added, then the run count, the lowest `cp` on the wall and `cp` at the
top read back.

## A run table

```matlab
study = gamut.create('sweep.gamut', 'writer', 'example sweep', ...
    'parameters', struct('alpha', struct('units', 'degree', 'role', 'condition')), ...
    'labels', struct('status', struct('role', 'status', 'categories', {{'converged', 'failed'}})), ...
    'scalars', struct('cl', '1'));
for alpha = 0:2:10
    study.addRun(struct('alpha', alpha, 'status', 'converged', 'cl', solve(alpha)));
end
study.close();

study = gamut.open('sweep.gamut', 'mode', 'a');
study.addRun(struct('alpha', 12, 'status', 'failed'));
study.close();

study = gamut.open('sweep.gamut');
cl = study.getScalar('cl', 'rows', study.select('status == converged'));
study.close();
```

```text
lift of the runs that converged: 0.00 0.22 0.44 0.66 0.88 1.10
```

`solve` stands for the solver. A run left without a result, such as the
failed one here, stores it as missing (`NaN`), and `select` returns
positions counted from 1. `'rows'` left out, or `':'`, is every row, and
`[]` is none, so the rows of a `select` that matched nothing read nothing.

## On one mesh

### Writing

```matlab
study = gamut.create('cylinder.gamut', 'writer', 'example sweep', 'mesh', 'shared', 'per', 'fixed', ...
    'coordinates', struct('units', 'm', 'axes', 2), ...
    'parameters', struct('gamma', struct('units', 'm2 s-1', 'role', 'design')), ...
    'meshLabels', struct('surface', struct('at', 'node', 'categories', {{'field', 'wall'}})), ...
    'fields', struct('cp', struct('units', '1', 'at', 'node')));
study.setMesh(points, cells, struct('surface', surface));
for gamma = linspace(0, 3.5, 8)
    study.addRun(struct('gamma', gamma), 'fields', struct('cp', solve(gamma)));
end
study.close();

study = gamut.open('cylinder.gamut', 'mode', 'a');
study.addRun(struct('gamma', 4), 'fields', struct('cp', solve(4)));
study.close();
```

Declarations are structs, one field per name. Cells are a cell array
`{types, offsets, connectivity}`, in VTK's convention as in every
language: the node numbers inside `connectivity` count from 0. The
`surface` label marks the wall's nodes with code 1, its place in
`categories` minus one. `solve` stands for the solver and returns `cp`
at every node. `gamut.open(path, 'mode', 'a')` reopens a file to add
runs.

### Reading

```matlab
study = gamut.open('cylinder.gamut');
fprintf('%s mesh, %d runs, %d nodes\n', study.type(), study.rowCount(), size(study.getPoints(), 1));
wall = find(strcmp(study.categories('surface'), 'wall')) - 1;  % the code that means 'wall'
onWall = find(study.getMeshLabel('surface') == wall);
lowest = min(study.getField('cp', 'nodes', onWall), [], 2);    % runs x wall nodes; each run's lowest
fprintf('lowest cp on the wall, by run:%s\n', sprintf(' %.2f', lowest));
top = study.getField('cp', 'nodes', 13);                       % node 13, the top, in every run
study.close();
fprintf('cp at the top of the cylinder, run by run:%s\n', sprintf(' %.2f', top));
```

```text
shared mesh, 9 runs, 576 nodes
lowest cp on the wall, by run: -3.00 -3.32 -3.66 -4.01 -4.37 -4.75 -5.14 -5.54 -5.95
cp at the top of the cylinder, run by run: -3.00 -2.69 -2.39 -2.10 -1.83 -1.57 -1.32 -1.08 -0.86
```

Node 13 here is node 12 in Python: positions count from 1 in MATLAB and
from 0 in Python. A label or mesh label's stored codes count from 0 in
every language, so a zone's code is its place in `categories` minus one.

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
([`examples/matlab/read_with_ncread.m`](../../examples/matlab/read_with_ncread.m)
is the whole program).

## Inputs outside a model's range

`gamut.evaluate` evaluates a [model file](07-models.md) and returns its
answer, a study open to read. An input outside the range the model was
fitted on is evaluated with a warning (`gamut:W4`), and the answer keeps
the model's bounds, so it can say which rows lie outside and how far.
[`evaluate_model.m`](../../examples/matlab/evaluate_model.m) asks the
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

Next: [Julia](13-julia.md).

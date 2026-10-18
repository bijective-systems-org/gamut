# 12. MATLAB

MATLAB reads and writes the same files with the same calls, in MATLAB's
spelling: methods on a study object in camelCase, options as name–value
pairs, declarations as structs, and positions counted from 1. Installing
the package takes one build step ([installing](../install.md#matlab)).

The example writes eight runs of flow past a cylinder on one mesh, reopens
the file to add a ninth, then reads the runs that meet a condition: the program of the
[README](../../README.md#example). From a working folder, with
`examples/matlab` on the path, run `one_mesh`.

## Writing

```matlab
study = gamut.create('cylinder.gamut', 'writer', 'example sweep', 'mesh', 'shared', 'per', 'fixed', ...
    'coordinates', struct('units', 'm', 'axes', 2), ...
    'parameters', struct('gamma', struct('units', 'm2 s-1', 'role', 'design')), ...
    'fields', struct('cp', struct('units', '1', 'at', 'node')));
study.setMesh(points, cells);
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
language: the node numbers inside `connectivity` count from 0. `solve`
stands for the solver and returns `cp` at every node. `gamut.open(path,
'mode', 'a')` reopens a file to add runs.

## Reading

```matlab
study = gamut.open('cylinder.gamut');
rows = study.select('gamma > 2');
cp = study.getField('cp', 'rows', rows, 'nodes', 13);           % runs x nodes, from 1
study.close();
```

```text
cp on top of the cylinder where gamma > 2: -1.57 -1.32 -1.08 -0.86
```

Node 13 here is node 12 in Python: positions count from 1 in MATLAB and
from 0 in Python. A label or mesh label's stored codes count from 0 in
every language, so a zone's code is its place in `categories` minus one.

## The same calls

| Python | MATLAB |
|---|---|
| `gamut.create(path, writer=w, fields={...})` | `gamut.create(path, 'writer', w, 'fields', struct(...))` |
| `study.add_run(values, fields=...)` | `study.addRun(values, 'fields', ...)` |
| `study.get_field("p", rows=r, nodes=n)` | `study.getField('p', 'rows', r, 'nodes', n)` |
| `study.select("mach > 0.7")` | `study.select('mach > 0.7')`, positions from 1 |
| `study.row_count` | `study.rowCount()` |
| `study.table()` | `study.table()`: a MATLAB `table`, labels as `categorical` |
| `gamut.register_model_type(cls)` | `gamut.registerModelType(className)` |
| `gamut.append`, `extract`, `write_copy`, `validate` | `gamut.append`, `extract`, `writeCopy`, `validate` |

`help gamut.Study` describes the study object, and `methods(study)` lists
what it can do.

## Notes

- A file written by MATLAB is the same file Python, Julia and C read: the
  library underneath is one and the same.
- MATLAB loads its own HDF5. Build the gateway against a core with HDF5
  linked in, such as the one inside the Python wheel, so the two never
  meet ([installing](../install.md#matlab)).
- Values arrive in the units they were stored in, which
  `study.describe(name).units` names. Converting them is left to the
  caller; only Python's reads convert, through pint.
- Keep names, table entries and labels to ASCII if MATLAB will read the
  file; the format allows any UTF-8.

Next: [Julia](13-julia.md).

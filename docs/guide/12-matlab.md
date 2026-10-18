# 12. MATLAB

MATLAB reads and writes the same files with the same calls, in MATLAB's
spelling: methods on a study object in camelCase, options as name–value
pairs, declarations as structs, and positions counted from 1. Installing
the package takes one build step ([installing](../install.md#matlab)).

The example writes and reads the study of [page 2](02-one-mesh.md). From
a working folder, with `examples/matlab` on the path, run `one_mesh`.

## Writing

```matlab
study = gamut.create('cylinder.gamut', 'writer', 'example sweep', 'mesh', 'shared', 'per', 'fixed', ...
    'coordinates', struct('units', 'm', 'axes', 2), ...
    'parameters', struct('gamma', struct('units', 'm2 s-1', 'role', 'design')), ...
    'meshLabels', struct('surface', struct('at', 'node', 'categories', {{'field', 'wall'}})), ...
    'fields', struct('cp', struct('units', '1', 'at', 'node')));
study.setMesh(points, cells, struct('surface', surface));
for gamma = linspace(0, 4, 9)
    uTheta = -sin(t) .* (1 + 1 ./ r.^2) + gamma ./ (2 * pi * r);
    uR = cos(t) .* (1 - 1 ./ r.^2);
    study.addRun(struct('gamma', gamma), 'fields', struct('cp', 1 - (uR.^2 + uTheta.^2)));
end
study.close();
```

Cells are a cell array `{types, offsets, connectivity}`, in VTK's
convention as in every language: the node numbers inside `connectivity`
count from 0.

## Reading

```matlab
study = gamut.open('cylinder.gamut');
fprintf('%s mesh, %d runs, %d nodes\n', study.type(), study.rowCount(), size(study.getPoints(), 1));
cp = study.getField('cp');                                       % runs x nodes
fprintf('cp block: %d x %d\n', size(cp));
wall = find(strcmp(study.categories('surface'), 'wall')) - 1;   % the code that means "wall"
onWall = find(study.getMeshLabel('surface') == wall);
lowest = min(study.getField('cp', 'nodes', onWall), [], 2);
fprintf('lowest cp on the wall, by run: %s\n', mat2str(round(lowest', 2)));
fprintf('one node across every run: %s\n', mat2str(round(study.getField('cp', 'nodes', 13)', 2)));
study.close();
```

It prints the numbers [page 2](02-one-mesh.md) shows. Node 13 here is
node 12 there: positions count from 1 in MATLAB and from 0 in Python. A
label or mesh label's stored codes count from 0 in every language, which
is why `wall` subtracts one from its place in the table.

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

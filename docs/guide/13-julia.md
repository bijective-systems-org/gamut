# 13. Julia

Julia reads and writes the same files with the same calls, in Julia's
spelling: functions in the `Gamut` module taking the study first,
declarations as `Dict`s or named tuples, `do` blocks that close the file,
and positions counted from 1. The package needs the core library
([installing](../install.md#julia)).

There are two examples: `sweep.jl`, the [README](../../README.md#example)'s
run table, and `one_mesh.jl`, eight runs of flow past a cylinder on one
mesh, with a ninth added and one node read in every run. From a working
folder: `julia --project=<checkout>/julia <checkout>/examples/julia/sweep.jl`.

## A run table

```julia
Gamut.create("sweep.gamut"; writer="example sweep",
              parameters=Dict("alpha" => (units="degree", role="condition")),
              labels=Dict("status" => (role="status", categories=["converged", "failed"])),
              scalars=Dict("cl" => "1")) do study
    for alpha in 0.0:2.0:10.0
        Gamut.add_run!(study, Dict("alpha" => alpha, "status" => "converged", "cl" => solve(alpha)))
    end
end

Gamut.open("sweep.gamut"; mode="a") do study
    Gamut.add_run!(study, Dict("alpha" => 12.0, "status" => "failed"))
end

cl = Gamut.open("sweep.gamut") do study
    Gamut.get_scalar(study, "cl"; rows=Gamut.select(study, "status == converged"))
end
```

```text
lift of the runs that converged: 0.00 0.22 0.44 0.66 0.88 1.10
```

`solve` stands for the solver. A run left without a result, such as the
failed one here, stores it as missing (`NaN`), and `select` returns
positions counted from 1.

## On one mesh

### Writing

```julia
Gamut.create("cylinder.gamut"; writer="example sweep", mesh="shared", per="fixed",
              coordinates=(units="m", axes=2),
              parameters=Dict("gamma" => (units="m2 s-1", role="design")),
              mesh_labels=Dict("surface" => (at="node", categories=["field", "wall"])),
              fields=Dict("cp" => (units="1", at="node"))) do study
    Gamut.set_mesh!(study; points, cells, labels=Dict("surface" => surface))
    for gamma in range(0, 3.5; length=8)
        Gamut.add_run!(study, Dict("gamma" => gamma); fields=Dict("cp" => solve(gamma)))
    end
end

Gamut.open("cylinder.gamut"; mode="a") do study
    Gamut.add_run!(study, Dict("gamma" => 4.0); fields=Dict("cp" => solve(4.0)))
end
```

`points` is nodes × axes; `cells` is a tuple `(types, offsets,
connectivity)`, in VTK's convention as in every language: the node numbers
inside `connectivity` count from 0. The `do` block finishes the file when
it ends, and removes it if the block throws and the file cannot be
finished. `solve` stands for the solver and returns `cp` at every node,
and `Gamut.open(path; mode="a")` reopens a file to add runs.

### Reading

```julia
Gamut.open("cylinder.gamut") do study
    println(study.type, " mesh, ", study.row_count, " runs, ", size(Gamut.get_points(study), 1), " nodes")
    wall = findfirst(==("wall"), Gamut.categories(study, "surface")) - 1   # the code that means "wall"
    on_wall = findall(==(wall), vec(Gamut.get_mesh_label(study, "surface")))
    lowest = minimum(Gamut.get_field(study, "cp"; nodes=on_wall); dims=2)  # runs × wall nodes, per run
    println("lowest cp on the wall, by run: ", join((@sprintf("%.2f", v) for v in lowest), " "))
    top = Gamut.get_field(study, "cp"; nodes=[13])                         # node 13, the top, in every run
    println("cp at the top of the cylinder, run by run: ", join((@sprintf("%.2f", v) for v in top), " "))
end
```

```text
shared mesh, 9 runs, 576 nodes
lowest cp on the wall, by run: -3.00 -3.32 -3.66 -4.01 -4.37 -4.75 -5.14 -5.54 -5.95
cp at the top of the cylinder, run by run: -3.00 -2.69 -2.39 -2.10 -1.83 -1.57 -1.32 -1.08 -0.86
```

Node 13 here is node 12 in Python: positions count from 1 in Julia and
from 0 in Python. Arrays come back with the axes in their logical order,
`cp[run, node]`. A mesh label's stored codes count from 0 in every
language, so the wall's code is its place in `categories` minus one.

## Inputs outside a model's range

`Gamut.evaluate` evaluates a [model file](07-models.md) and returns its
answer, a study open to read. An input outside the range the model was
fitted on is evaluated with a warning (W4), and the answer keeps the
model's bounds, so it can say which rows lie outside and how far.
[`nearest.jl`](../../examples/julia/nearest.jl) asks the models page's
nearest-run model about 5 and 12 degrees:

```julia
answer = Gamut.evaluate("lift_nearest.gamut", Dict("alpha" => [5.0, 12.0]))
outside = Gamut.outside(answer, "alpha")
close(answer)
```

```text
degrees outside the fitted range: 0 2
```

`outside` gives a number per row in the parameter's units: 0 inside the
bounds or on one, negative below them, positive above.

## The same calls

| Python | Julia |
|---|---|
| `with gamut.create(path, writer=w, ...) as study:` | `Gamut.create(path; writer=w, ...) do study` |
| `study.add_run(values, fields=...)` | `Gamut.add_run!(study, values; fields=...)` |
| `study.get_field("p", rows=r, nodes=n)` | `Gamut.get_field(study, "p"; rows=r, nodes=n)` |
| `study.select("mach > 0.7")` | `Gamut.select(study, "mach > 0.7")`, positions from 1 |
| `study.outside("alpha", rows=r)` | `Gamut.outside(study, "alpha"; rows=r)` |
| `study.row_count`, `study.type` | `study.row_count`, `study.type` |
| `study.model_numbers("fit")` | `Gamut.model_numbers(study, "fit")` |
| `gamut.append`, `extract`, `write_copy`, `validate` | `Gamut.append!`, `extract`, `write_copy`, `validate` |

## Notes

- Values arrive in the units they were stored in, which
  `Gamut.describe(study, name)["units"]` names. Converting them is left
  to the caller; only Python's reads convert, through pint.
- Julia evaluates model files whose models are the built-in nearest
  neighbour; models of other types are registered in Python or MATLAB.
- `Gamut.library_path()` names the core library in use, set by
  `GAMUT_LIBRARY`.

Next: [C++ and C](14-c-and-cpp.md).

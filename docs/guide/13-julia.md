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
              fields=Dict("cp" => (units="1", at="node"))) do study
    Gamut.set_mesh!(study; points, cells)
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
cp = Gamut.open("cylinder.gamut") do study
    Gamut.get_field(study, "cp"; nodes=[13])                 # runs × nodes, from 1
end
```

```text
cp at the top of the cylinder, run by run: -3.00 -2.69 -2.39 -2.10 -1.83 -1.57 -1.32 -1.08 -0.86
```

Node 13 here is node 12 in Python: positions count from 1 in Julia and
from 0 in Python. Arrays come back with the axes in their logical order,
`cp[run, node]`.

## The same calls

| Python | Julia |
|---|---|
| `with gamut.create(path, writer=w, ...) as study:` | `Gamut.create(path; writer=w, ...) do study` |
| `study.add_run(values, fields=...)` | `Gamut.add_run!(study, values; fields=...)` |
| `study.get_field("p", rows=r, nodes=n)` | `Gamut.get_field(study, "p"; rows=r, nodes=n)` |
| `study.select("mach > 0.7")` | `Gamut.select(study, "mach > 0.7")`, positions from 1 |
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

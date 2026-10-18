# 13. Julia

Julia reads and writes the same files with the same calls, in Julia's
spelling: functions in the `Mestra` module taking the study first,
declarations as `Dict`s or named tuples, `do` blocks that close the file,
and positions counted from 1. The package needs the core library
([installing](../install.md#julia)).

The example writes and reads the study of [page 2](02-one-mesh.md). From a
working folder: `julia --project=<checkout>/julia <checkout>/examples/julia/one_mesh.jl`.

## Writing

```julia
Mestra.create("cylinder.mes"; writer="example sweep", mesh="shared", per="fixed",
              coordinates=(units="m", axes=2),
              parameters=Dict("gamma" => (units="m2 s-1", role="design")),
              mesh_labels=Dict("surface" => (at="node", categories=["field", "wall"])),
              fields=Dict("cp" => (units="1", at="node"))) do study
    Mestra.set_mesh!(study; points, cells, labels=Dict("surface" => surface))
    for gamma in range(0, 4; length=9)
        u_theta = -sin.(t) .* (1 .+ 1 ./ r .^ 2) .+ gamma ./ (2π .* r)
        u_r = cos.(t) .* (1 .- 1 ./ r .^ 2)
        Mestra.add_run!(study, Dict("gamma" => gamma); fields=Dict("cp" => 1 .- (u_r .^ 2 .+ u_theta .^ 2)))
    end
end
```

`points` is nodes × axes; `cells` is a tuple `(types, offsets,
connectivity)`, in VTK's convention as in every language: the node numbers
inside `connectivity` count from 0. The `do` block finishes the file when
it ends, and removes it if the block throws and the file cannot be
finished.

## Reading

```julia
Mestra.open("cylinder.mes") do study
    println(study.type, " mesh, ", study.row_count, " runs, ", size(Mestra.get_points(study), 1), " nodes")
    cp = Mestra.get_field(study, "cp")                         # runs × nodes
    println("cp block: ", size(cp))
    wall = findfirst(==("wall"), Mestra.categories(study, "surface")) - 1   # the code that means "wall"
    on_wall = findall(==(wall), Mestra.get_mesh_label(study, "surface"))
    lowest = minimum(Mestra.get_field(study, "cp"; nodes=on_wall); dims=2)
    println("lowest cp on the wall, by run: ", round.(vec(lowest); digits=2))
    println("one node across every run: ", round.(vec(Mestra.get_field(study, "cp"; nodes=[13])); digits=2))
end
```

It prints the numbers [page 2](02-one-mesh.md) shows. Node 13 here is node
12 there: positions count from 1 in Julia and from 0 in Python. Arrays come
back with the axes in their logical order, `cp[run, node]`.

## The same calls

| Python | Julia |
|---|---|
| `with mestra.create(path, writer=w, ...) as study:` | `Mestra.create(path; writer=w, ...) do study` |
| `study.add_run(values, fields=...)` | `Mestra.add_run!(study, values; fields=...)` |
| `study.get_field("p", rows=r, nodes=n)` | `Mestra.get_field(study, "p"; rows=r, nodes=n)` |
| `study.select("mach > 0.7")` | `Mestra.select(study, "mach > 0.7")`, positions from 1 |
| `study.row_count`, `study.type` | `study.row_count`, `study.type` |
| `mestra.append`, `extract`, `write_copy`, `validate` | `Mestra.append!`, `extract`, `write_copy`, `validate` |

## Worth knowing

- Values arrive in the units they were stored in, which
  `Mestra.describe(study, name)["units"]` names. Converting them is left
  to the caller; only Python's reads convert, through pint.
- Julia evaluates model files whose models are the built-in nearest
  neighbour; models of other types are registered in Python or MATLAB.
- `Mestra.library_path()` names the core library in use, set by
  `MESTRA_LIBRARY`.

Next: [C and C++](14-c-and-cpp.md).

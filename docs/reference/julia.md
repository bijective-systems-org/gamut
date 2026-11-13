# Julia

Julia reads and writes the same files with the same calls, in Julia's
spelling: functions in the `GamutFile` module taking the study first,
declarations as `Dict`s or named tuples, `do` blocks that close the file,
and positions counted from 1. The package is named `GamutFile`, after
Julia's convention for file-format packages; the format and the other
languages keep `gamut`. It needs the core library
([installing](../install.md)). An example written in Julia has a
Julia tab, quoted from a program in `examples/julia`; the
[examples](../guide/README.md) say which are. Run one from a working
folder with `julia --project=<checkout>/julia <checkout>/examples/julia/run_table.jl`.

## The same calls

| Python | Julia |
|---|---|
| `with gamut.create(path, writer=w, ...) as study:` | `GamutFile.create(path; writer=w, ...) do study` |
| `study.add_run(values, fields=...)` | `GamutFile.add_run!(study, values; fields=...)` |
| `study.get_field("p", rows=r, nodes=n)` | `GamutFile.get_field(study, "p"; rows=r, nodes=n)` |
| `study.select("mach > 0.7")` | `GamutFile.select(study, "mach > 0.7")`, positions from 1 |
| `study.outside("alpha", rows=r)` | `GamutFile.outside(study, "alpha"; rows=r)` |
| `study.row_count`, `study.type` | `study.row_count`, `study.type` |
| `study.related("cl")` | `GamutFile.related(study, "cl")` |
| `study.model_numbers("fit")` | `GamutFile.model_numbers(study, "fit")` |
| `gamut.append`, `extract`, `write_copy`, `validate` | `GamutFile.append!`, `extract`, `write_copy`, `validate` |
| `gamut.set_marking_notice(show)` | `GamutFile.set_marking_notice(show)`: `true` logs with `@info` |

## Conventions

Declarations are `Dict`s whose values are named tuples, `(units="degree",
role="condition")`, or a units string alone for a result. `select` returns
positions counted from 1, and every read takes them as `rows`; arrays come
back with their axes in logical order, `cp[run, node]`. Cells are a tuple
`(types, offsets, connectivity)` in VTK's convention, as in every
language, so the node numbers inside `connectivity` count from 0, and the
stored codes of a label or mesh label count from 0 too: a zone's code is
its place in `categories` minus one. A `do` block finishes the file when
it ends, and removes it if the block throws and the file cannot be
finished. A refusal throws a `GamutError` that names the rule.

## Inputs outside a model's range

`GamutFile.evaluate` evaluates a [model file](../guide/07-models.md) and returns its
answer, a study open to read. An input outside the range the model was
fitted on is evaluated with a warning (W4), and the answer keeps the
model's bounds, so it can say which rows lie outside and how far.
[`nearest.jl`](https://github.com/bijective-systems-org/gamut/blob/main/examples/julia/nearest.jl) asks the models page's
nearest-run model about 5 and 12 degrees:

```julia
answer = GamutFile.evaluate("lift_nearest.gamut", Dict("alpha" => [5.0, 12.0]))
outside = GamutFile.outside(answer, "alpha")
close(answer)
```

```text
degrees outside the fitted range: 0 2
```

`outside` gives a number per row in the parameter's units: 0 inside the
bounds or on one, negative below them, positive above.

## Notes

- Values arrive in the units they were stored in, which
  `GamutFile.describe(study, name)["units"]` names. Converting them is left
  to the caller; only Python's reads convert, through pint.
- Julia evaluates model files whose models are the built-in nearest
  neighbour; models of other types are registered in Python or MATLAB.
- `GamutFile.library_path()` names the core library in use, set by
  `GAMUT_LIBRARY`.

Next: [C++ and C](c-and-cpp.md).

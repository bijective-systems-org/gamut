# Rust

Rust reads and writes the same files with the same calls, in Rust's
spelling: a `Study` that owns the open file and closes it when dropped,
methods that return a `Result` whose error names the rule, slices for
values, and positions counted from 0. The `bijective-gamut` crate, `gamut`
in code, is a thin layer over `bijective-gamut-sys`, the declarations of
`gamut.h`, and links the core
library ([installing](../install.md)). An example written in Rust has a
Rust tab, quoted from a program in `examples/rust`; the
[examples](../guide/README.md) say which are. Run one from `rust/` in a
checkout with `cargo run --example run_table`.

## The same calls

| Python | Rust |
|---|---|
| `gamut.create(path, writer=w, mesh="shared", per="fixed", ...)` | `gamut::create(path, w, "shared", "fixed")?`, then `declare_...` calls; `"", ""` for a table of runs |
| `study.add_run(values, fields=...)` | `study.add_run(&[("gamma", 0.5.into())], &[("cp", &cp)])?` |
| `study.add_runs(columns)` | `study.add_runs(&[("alpha", alpha.into()), ...], &[])?` |
| `gamut.open(path)`, `gamut.open(path, mode="a")` | `gamut::open(path)?`, `gamut::open_append(path)?` |
| `study.get_field("p", rows=r, nodes=n)` | `study.get_field("p", r, n)?`: `..` for every one, `2..5`, a `Vec` of positions, or one position |
| `study.get_parameter("alpha")` | `study.get_parameter::<f64>("alpha", ..)?`: `i64` for one declared int64 |
| `study.row_count`, `study.type` | `study.row_count()?`, `study.type_()?` |
| `study.related("cl")` | `study.related("cl")?`: a `gamut::Related` |
| `gamut.evaluate(path, inputs, path=out)` | `gamut::evaluate(path, &inputs, out)?`: the answer and the W4 findings |
| `gamut.append`, `extract`, `write_copy`, `validate` | `gamut::append`, `extract`, `write_copy`, `validate` |

## Conventions

A run's values are pairs of a name and a `gamut::Value`, made with
`.into()` from an `f64`, an `i64` or a label's name; many runs' are pairs
of a name and a `gamut::Column`, from a `Vec`. A parameter is float64
unless declared otherwise: `declare_parameter_with` takes a
`gamut::Parameter` that says `.int64()`, `.bounds(lower, upper)` or, for
time, `.run_group(label)`. A result that describes another is declared
with `declare_scalar_of` or `declare_field_of` and `gamut::std_of`,
`quantile_of` or `derivative_of`. Reads come back as a `Vec`, or as a
`gamut::Array` with its `shape` for a field, indexed `cp[[run, node]]`.
Cells are a `gamut::Cells` in VTK's convention, as in every language.

`close` finishes a file and says why when it cannot (a shared mesh never
set); the file stays open to fix and close again. A study dropped without
`close` is finished if it can be, and removed if it cannot.

## Inputs outside a model's range

`gamut::evaluate` evaluates a [model file](../guide/07-models.md) into a
new data file and returns it open to read, with the W4 findings for inputs
outside the range the model was fitted on, which are evaluated. The answer
keeps the model's bounds, so it can say which rows lie outside and how
far. [`nearest.rs`](https://github.com/bijective-systems-org/gamut/blob/main/examples/rust/nearest.rs)
asks the models page's nearest-run model about 5 and 12 degrees:

```rust
let (answer, warnings) =
    gamut::evaluate("lift_nearest.gamut", &[("alpha", vec![5.0, 12.0].into())], "nearest_outside.gamut")?;
for warning in warnings {
    eprintln!("{warning}");
}
let outside = answer.outside("alpha", ..)?;
```

```text
degrees outside the fitted range: 0 2
```

`outside` gives a number per row in the parameter's units: 0 inside the
bounds or on one, negative below them, positive above.

## Notes

- Values arrive in the units they were stored in, which
  `study.describe(name)?["units"]` names. Converting them is left to the
  caller; only Python's reads convert, through pint.
- Rust evaluates model files whose models are the built-in nearest
  neighbour; models of other types are registered in Python or MATLAB.
  The crate writes data files, not model files.
- `study.handle()` gives the open file to the calls of `gamut.h` the
  crate does not cover, through `bijective-gamut-sys` (`gamut_sys`).
- The crates carry the version of the core they are made for, and are
  added from the same release tag.

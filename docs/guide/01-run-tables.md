# 1. Run tables

The simplest study has no mesh: a list of runs, each with the inputs that
define it and the numbers it produced. A wing's polar is one. The example
sweeps Mach number and angle of attack, records whether each run
converged, and keeps the lift and drag coefficients.

## Writing

A file is created with everything it will hold declared up front: each
name, its units and its role. Nothing is guessed later from the data.

```python
with mestra.create("polar.mes", writer="example sweep",
                   parameters={"mach": {"units": "1", "role": "condition"},
                               "alpha": {"units": "degree", "role": "condition"}},
                   labels={"status": {"role": "status", "categories": ["converged", "failed"]}},
                   scalars={"cl": "1", "cd": "1"},
                   constants={"reference_area": (12.5, "m2")},
                   title="Wing A polar") as study:
```

- **Parameters** place a run in the study. Their role is `condition` (how
  it is operated: Mach, incidence, altitude), `design` (the shape: a
  geometry or design variable) or `time`. Tools use the role: a geometry
  model takes the design parameters, a viewer animates time.
- **Labels** name rather than measure. A label with the role `status` says
  which runs can be trusted; tools that train on the data skip the rest
  unless told otherwise.
- **Scalars** are results with one value per run.
- **Constants** hold one value for the whole study.

Units are required on every number. They use the grammar of UDUNITS, as
netCDF and CF do: `1` for dimensionless, `degree`, `m s-1`, `W m-2`.
`"cl": "1"` is short for `{"units": "1"}`.

Each run then gives every parameter, label and scalar by name, a label by
one of its category names:

```python
study.add_run({"mach": mach, "alpha": float(alpha),
               "status": "failed" if failed else "converged",
               "cl": np.nan if failed else cl, "cd": np.nan if failed else cd})
```

A result a run does not have is NaN. Parameters and labels are never
missing.

Leaving the `with` block finishes the file. If the block ends with an
error, the runs added so far are kept when the file can still be finished,
and the file is removed when it cannot.

## Reading

```python
with mestra.open("polar.mes") as study:
    print(study.row_count, "runs;", study.describe()["title"])
    print("lift at Mach 0.7:", study.get_scalar("cl", rows=study.select("mach == 0.7")).round(3))
    print("runs that failed:", study.select("status == failed"))
    print("reference area:", study.get_constant("reference_area"), study.describe("reference_area")["units"])
```

```text
18 runs; Wing A polar
lift at Mach 0.7: [-0.308  0.     0.308  0.616  0.924  1.232]
runs that failed: [17]
reference area: 12.5 m2
```

`select` takes a condition and returns the positions of the rows that meet
it; every `get_` call takes such positions as `rows`. Conditions compare
parameters, scalars and labels, joined by `and`, `or` and `not`
([selecting runs](../reference/selecting.md)). `describe` returns what the
file says about a name, or about the file itself.

## Worth knowing

- Every row gets an id when it is written, unique in the file and never
  reused. A run keeps its id when it is copied to another file
  ([combining files](09-combining-files.md)).
- `study.table()` returns the whole run table as columns, labels as names,
  ready for `pandas.DataFrame`.
- `mestra validate polar.mes` reports the failed run and its missing
  results as warnings, so whoever receives the file sees them without
  being told.

Run it: `python examples/01_run_table.py`. Next: [one mesh](02-one-mesh.md).

# 1. Run tables

The simplest study has no mesh: a list of runs, each with the inputs that
define it and the numbers it produced. A wing's polar is one. The example
sweeps Mach number and angle of attack, records whether each run
converged, and keeps the lift and drag coefficients. It is the same
program in each language.

## Writing

A file is created with everything it will hold declared up front: each
name, its units and its role. Nothing is guessed later from the data.

/// tab | Python

```python
with gamut.create("polar.gamut", writer="example sweep",
                   parameters={"mach": {"units": "1", "role": "condition"},
                               "alpha": {"units": "degree", "role": "condition"}},
                   labels={"status": {"role": "status", "categories": ["converged", "failed"]}},
                   scalars={"cl": "1", "cd": "1"},
                   constants={"reference_area": (12.5, "m2")},
                   title="Wing A polar") as study:
```

///

/// tab | MATLAB

```matlab
study = gamut.create('polar.gamut', 'writer', 'example sweep', ...
    'parameters', struct('mach', struct('units', '1', 'role', 'condition'), ...
                         'alpha', struct('units', 'degree', 'role', 'condition')), ...
    'labels', struct('status', struct('role', 'status', 'categories', {{'converged', 'failed'}})), ...
    'scalars', struct('cl', '1', 'cd', '1'), ...
    'constants', struct('reference_area', {{12.5, 'm2'}}), ...
    'title', 'Wing A polar');
```

///

/// tab | Julia

```julia
Gamut.create("polar.gamut"; writer="example sweep",
              parameters=Dict("mach" => (units="1", role="condition"),
                              "alpha" => (units="degree", role="condition")),
              labels=Dict("status" => (role="status", categories=["converged", "failed"])),
              scalars=Dict("cl" => "1", "cd" => "1"),
              constants=Dict("reference_area" => (12.5, "m2")),
              title="Wing A polar") do study
```

///

/// tab | C++

```cpp
auto study = gamut::create("polar.gamut", "example sweep");
study.declare_parameter("mach", "condition", "1");
study.declare_parameter("alpha", "condition", "degree");
study.declare_label("status", "status", {"converged", "failed"});
study.declare_scalar("cl", "1");
study.declare_scalar("cd", "1");
study.set_constant("reference_area", 12.5, "m2");
study.set_attribute("title", "Wing A polar");
```

///

/// tab | Rust

```rust
let mut study = gamut::create("polar.gamut", "example sweep", "", "")?;
study.declare_parameter("mach", "condition", "1")?;
study.declare_parameter("alpha", "condition", "degree")?;
study.declare_label("status", "status", &["converged", "failed"])?;
study.declare_scalar("cl", "1")?;
study.declare_scalar("cd", "1")?;
study.set_constant("reference_area", 12.5, "m2")?;
study.set_attribute("title", "Wing A polar")?;
```

///

Parameters place a run in the study. Their role is `condition` (how it is
operated: Mach, incidence, altitude), `design` (the shape: a geometry or
design variable) or `time`. Tools use the role: a geometry model takes the
design parameters, a viewer animates time. Labels name rather than
measure; a label with the role `status` says which runs can be trusted.
A run is usable when its status is `converged`, the one name with that
meaning (`failed` and `partial` are the usual others), and tools that
train on the data skip the rest unless told otherwise. Scalars are
results with one value per run, and constants hold one value for the
whole study.

Units are required on every number. They use the grammar of UDUNITS, as
netCDF and CF do: `1` for dimensionless, `degree`, `m s-1`, `W m-2`.
`"cl": "1"` is short for `{"units": "1"}`, in every language. The grammar
is checked when the file is written, the names are not: a misspelt
`dgree` is stored as given, and is caught only when a read converts it
([units](08-reading-parts.md#units)).

Each run then gives every parameter, label and scalar by name, a label by
one of its category names:

/// tab | Python

```python
for mach in (0.6, 0.7, 0.8):
    for alpha in range(-2, 9, 2):
        cl = 0.11 * alpha / np.sqrt(1 - mach**2)        # stand-in for a solver
        cd = 0.008 + 0.04 * cl**2
        failed = mach == 0.8 and alpha == 8
        study.add_run({"mach": mach, "alpha": float(alpha),
                       "status": "failed" if failed else "converged",
                       "cl": np.nan if failed else cl, "cd": np.nan if failed else cd})
```

///

/// tab | MATLAB

```matlab
for mach = [0.6 0.7 0.8]
    for alpha = -2:2:8
        cl = 0.11 * alpha / sqrt(1 - mach^2);           % stand-in for a solver
        cd = 0.008 + 0.04 * cl^2;
        if mach == 0.8 && alpha == 8
            study.addRun(struct('mach', mach, 'alpha', alpha, 'status', 'failed', 'cl', NaN, 'cd', NaN));
        else
            study.addRun(struct('mach', mach, 'alpha', alpha, 'status', 'converged', 'cl', cl, 'cd', cd));
        end
    end
end
study.close();
```

///

/// tab | Julia

```julia
    for mach in (0.6, 0.7, 0.8), alpha in -2.0:2.0:8.0
        cl = 0.11 * alpha / sqrt(1 - mach^2)          # stand-in for a solver
        cd = 0.008 + 0.04 * cl^2
        failed = mach == 0.8 && alpha == 8
        Gamut.add_run!(study, Dict("mach" => mach, "alpha" => alpha,
                                   "status" => failed ? "failed" : "converged",
                                   "cl" => failed ? NaN : cl, "cd" => failed ? NaN : cd))
    end
end
```

///

/// tab | C++

```cpp
for (const double mach : {0.6, 0.7, 0.8}) {
  for (int alpha = -2; alpha <= 8; alpha += 2) {
    const double cl = 0.11 * alpha / std::sqrt(1 - mach * mach);  // stand-in for a solver
    const double cd = 0.008 + 0.04 * cl * cl;
    const bool failed = mach == 0.8 && alpha == 8;
    study.add_run({{"mach", mach}, {"alpha", double(alpha)},
                   {"status", failed ? "failed" : "converged"},
                   {"cl", failed ? NAN : cl}, {"cd", failed ? NAN : cd}});
  }
}
study.close();
```

///

/// tab | Rust

```rust
for mach in [0.6_f64, 0.7, 0.8] {
    for alpha in (-2..=8).step_by(2).map(f64::from) {
        let cl = 0.11 * alpha / (1.0 - mach * mach).sqrt(); // stand-in for a solver
        let cd = 0.008 + 0.04 * cl * cl;
        let failed = mach == 0.8 && alpha == 8.0;
        study.add_run(&[("mach", mach.into()), ("alpha", alpha.into()),
                        ("status", if failed { "failed" } else { "converged" }.into()),
                        ("cl", if failed { f64::NAN } else { cl }.into()),
                        ("cd", if failed { f64::NAN } else { cd }.into())], &[])?;
    }
}
study.close()?;
```

///

A result a run does not have is NaN, and so is one it leaves out.
Parameters and labels are never missing. A category name a label has not
seen is added to its categories, so a misspelt `"convereged"` becomes a
new category rather than an error; `categories("status")` lists them.

Closing the file finishes it: leaving the `with` block in Python or the
`do` block in Julia, `close` in MATLAB, C++ and Rust. When a Python or Julia
block ends with an error, the runs added so far are kept if the file can
still be finished, and the file is removed if it cannot.

## Reading

/// tab | Python

```python
with gamut.open("polar.gamut") as study:
    print(f"{study.row_count} runs; {study.describe()['title']}")
    cl = study.get_scalar("cl", rows=study.select("mach == 0.7"))
    print("lift at Mach 0.7:", " ".join(f"{v:.3f}" for v in cl))
    failed = study.select("status == failed")
    mach, alpha = study.get_parameter("mach", rows=failed), study.get_parameter("alpha", rows=failed)
    print(f"failed: Mach {mach[0]:.1f}, alpha {alpha[0]:g} degree")
    area = study.get_constant("reference_area")
    print(f"reference area: {area:g} {study.describe('reference_area')['units']}")
```

///

/// tab | MATLAB

```matlab
study = gamut.open('polar.gamut');
fprintf('%d runs; %s\n', study.rowCount(), study.describe().title);
cl = study.getScalar('cl', 'rows', study.select('mach == 0.7'));
fprintf('lift at Mach 0.7: %s\n', strjoin(compose('%.3f', cl), ' '));
failed = study.select('status == failed');
mach = study.getParameter('mach', 'rows', failed);
alpha = study.getParameter('alpha', 'rows', failed);
fprintf('failed: Mach %.1f, alpha %g degree\n', mach, alpha);
fprintf('reference area: %g %s\n', study.getConstant('reference_area'), study.describe('reference_area').units);
study.close();
```

///

/// tab | Julia

```julia
Gamut.open("polar.gamut") do study
    println(study.row_count, " runs; ", Gamut.describe(study)["title"])
    cl = Gamut.get_scalar(study, "cl"; rows=Gamut.select(study, "mach == 0.7"))
    println("lift at Mach 0.7: ", join((@sprintf("%.3f", v) for v in cl), " "))
    failed = Gamut.select(study, "status == failed")
    mach = Gamut.get_parameter(study, "mach"; rows=failed)
    alpha = Gamut.get_parameter(study, "alpha"; rows=failed)
    @printf("failed: Mach %.1f, alpha %g degree\n", mach[1], alpha[1])
    @printf("reference area: %g %s\n", Gamut.get_constant(study, "reference_area"),
            Gamut.describe(study, "reference_area")["units"])
end
```

///

/// tab | C++

```cpp
study = gamut::open("polar.gamut");
std::printf("%lld runs; %s\n", (long long)study.row_count(), study.describe()["title"].c_str());
const std::vector<double> cl = study.get_scalar("cl", study.select("mach == 0.7"));
std::printf("lift at Mach 0.7:");
for (const double v : cl) std::printf(" %.3f", v);
std::printf("\n");
const auto failed = study.select("status == failed");
const double mach = study.get_parameter<double>("mach", failed)[0];
const double alpha = study.get_parameter<double>("alpha", failed)[0];
std::printf("failed: Mach %.1f, alpha %g degree\n", mach, alpha);
std::printf("reference area: %g %s\n", study.get_constant<double>("reference_area"),
            study.describe("reference_area")["units"].c_str());
```

///

/// tab | Rust

```rust
let study = gamut::open("polar.gamut")?;
println!("{} runs; {}", study.row_count()?, study.describe("")?["title"]);
let cl = study.get_scalar("cl", study.select("mach == 0.7")?)?;
println!("lift at Mach 0.7:{}", cl.iter().map(|v| format!(" {v:.3}")).collect::<String>());
let failed = study.select("status == failed")?;
let mach: Vec<f64> = study.get_parameter("mach", failed.clone())?;
let alpha: Vec<f64> = study.get_parameter("alpha", failed)?;
println!("failed: Mach {:.1}, alpha {} degree", mach[0], alpha[0]);
println!("reference area: {} {}", study.get_constant::<f64>("reference_area")?,
         study.describe("reference_area")?["units"]);
```

///

Each prints:

```text
18 runs; Wing A polar
lift at Mach 0.7: -0.308 0.000 0.308 0.616 0.924 1.232
failed: Mach 0.8, alpha 8 degree
reference area: 12.5 m2
```

`select` takes a condition and returns the positions of the rows that meet
it, counted from 0 in Python, C++ and Rust and from 1 in MATLAB and Julia; every
`get_` call takes such positions as its rows. Conditions compare
parameters, scalars and labels, joined by `and`, `or` and `not`
([selecting runs](../reference/selecting.md)). `describe` returns what the
file says about a name, or about the file itself.

## Notes

- `create` refuses a path that exists and leaves that file as it was. To
  add runs to a study, open it to append: `mode="a"` in Python and Julia,
  `'mode', 'a'` in MATLAB, `gamut::open(path, "a")` in C++,
  `gamut::open_append(path)` in Rust.
- Every row gets an id when it is written, unique in the file and never
  reused. Runs extracted to another file keep their ids; runs appended to
  another file get new ones there ([combining files](09-combining-files.md)).
- `add_runs` (`addRuns` in MATLAB) adds many runs at once from a column per
  name: a dict of arrays or a pandas DataFrame in Python, a `table` or a
  struct of columns in MATLAB. `table()` goes the other way: the whole run
  table as columns, labels as names.
- `gamut validate polar.gamut` reports the failed run and its missing
  results as warnings, so whoever receives the file sees them without
  being told.

Run it: `python examples/01_run_table.py`, or `run_table` from
`examples/matlab`, `examples/julia` and `examples/cpp`
([installing](../install.md) says how to run each). Next:
[one mesh](02-one-mesh.md).

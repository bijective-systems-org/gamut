# 6. Uncertainty and gradients

A result often comes with more than its value: a spread from an ensemble or
from an unsteady run, an interval, a derivative from an adjoint solver.
Each of these is a result of its own that names the result it describes,
so a reader finds it without relying on naming conventions.

The example stores, for each angle of attack, a lift coefficient with its
standard deviation, its 5 % and 95 % quantiles, and its derivative with
respect to angle of attack.

## Writing

/// tab | Python

```python
with gamut.create("uncertain.gamut", writer="example ensemble",
                   parameters={"alpha": {"units": "degree", "role": "condition"}},
                   scalars={"cl": "1",
                            "cl_std": {"units": "1", "of": "cl", "statistic": "std"},
                            "cl_p05": {"units": "1", "of": "cl", "statistic": "quantile", "q": 0.05},
                            "cl_p95": {"units": "1", "of": "cl", "statistic": "quantile", "q": 0.95},
                            "dcl_dalpha": {"units": "degree-1", "of": "cl",
                                           "with_respect_to": "alpha"}}) as study:
    spread = 0.01 + 0.002 * alpha
    study.add_runs({"alpha": alpha, "cl": cl, "cl_std": spread,
                    "cl_p05": cl - 1.645 * spread, "cl_p95": cl + 1.645 * spread,
                    "dcl_dalpha": np.full(9, 0.11)})
```

///

/// tab | MATLAB

```matlab
study = gamut.create('uncertain.gamut', 'writer', 'example ensemble', ...
    'parameters', struct('alpha', struct('units', 'degree', 'role', 'condition')), ...
    'scalars', struct('cl', '1', ...
        'cl_std', struct('units', '1', 'of', 'cl', 'statistic', 'std'), ...
        'cl_p05', struct('units', '1', 'of', 'cl', 'statistic', 'quantile', 'q', 0.05), ...
        'cl_p95', struct('units', '1', 'of', 'cl', 'statistic', 'quantile', 'q', 0.95), ...
        'dcl_dalpha', struct('units', 'degree-1', 'of', 'cl', 'withRespectTo', 'alpha')));
study.addRuns(struct('alpha', alpha, 'cl', cl, 'cl_std', spread, ...
    'cl_p05', cl - 1.645 * spread, 'cl_p95', cl + 1.645 * spread, 'dcl_dalpha', repmat(0.11, 9, 1)));
study.close();
```

///

/// tab | Julia

```julia
Gamut.create("uncertain.gamut"; writer="example ensemble",
              parameters=Dict("alpha" => (units="degree", role="condition")),
              scalars=Dict("cl" => "1",
                           "cl_std" => (units="1", of="cl", statistic="std"),
                           "cl_p05" => (units="1", of="cl", statistic="quantile", q=0.05),
                           "cl_p95" => (units="1", of="cl", statistic="quantile", q=0.95),
                           "dcl_dalpha" => (units="degree-1", of="cl", with_respect_to="alpha"))) do study
    Gamut.add_runs!(study, Dict("alpha" => alpha, "cl" => cl, "cl_std" => spread,
                                "cl_p05" => cl .- 1.645 .* spread, "cl_p95" => cl .+ 1.645 .* spread,
                                "dcl_dalpha" => fill(0.11, 9)))
end
```

///

/// tab | C++

```cpp
auto study = gamut::create("uncertain.gamut", "example ensemble");
study.declare_parameter("alpha", "condition", "degree");
study.declare_scalar("cl", "1");
study.declare_scalar("cl_std", "1", gamut::std_of("cl"));
study.declare_scalar("cl_p05", "1", gamut::quantile_of("cl", 0.05));
study.declare_scalar("cl_p95", "1", gamut::quantile_of("cl", 0.95));
study.declare_scalar("dcl_dalpha", "degree-1", gamut::derivative_of("cl", "alpha"));
study.add_runs({{"alpha", alpha}, {"cl", cl}, {"cl_std", spread}, {"cl_p05", p05}, {"cl_p95", p95},
                {"dcl_dalpha", std::vector<double>(9, 0.11)}});
study.close();
```

///

/// tab | Rust

```rust
let mut study = gamut::create("uncertain.gamut", "example ensemble", "", "")?;
study.declare_parameter("alpha", "condition", "degree")?;
study.declare_scalar("cl", "1")?;
study.declare_scalar_of("cl_std", "1", std_of("cl"))?;
study.declare_scalar_of("cl_p05", "1", quantile_of("cl", 0.05))?;
study.declare_scalar_of("cl_p95", "1", quantile_of("cl", 0.95))?;
study.declare_scalar_of("dcl_dalpha", "degree-1", derivative_of("cl", "alpha"))?;
study.add_runs(&[("alpha", alpha.into()), ("cl", cl.into()), ("cl_std", spread.into()), ("cl_p05", p05.into()),
                 ("cl_p95", p95.into()), ("dcl_dalpha", vec![0.11; 9].into())], &[])?;
study.close()?;
```

///

- `of` names the result being described.
- `statistic` is `std` (a standard deviation, never negative) or
  `quantile` with `q` between 0 and 1. A symmetric interval is two
  quantiles. Its units are those of the result it describes. In C++ and
  Rust, `std_of` and `quantile_of` make these declarations.
- A derivative names what it is taken with respect to (`with_respect_to`;
  `withRespectTo` in MATLAB, `derivative_of` in C++ and Rust): a parameter, as
  here, or node position (`coordinates` with an `axis`), which is an
  adjoint shape sensitivity stored as a node field per axis.
- Anything else, such as an RMS, a time average or a maximum, is an
  ordinary result with a descriptive name.

## Reading

/// tab | Python

```python
with gamut.open("uncertain.gamut") as study:
    related = study.related("cl")
    print("the std of cl:", related["std"])
    print("its 0.05 and 0.95 quantiles:", related["quantiles"][0.05], related["quantiles"][0.95])
    print("its derivative with respect to alpha:", related["derivatives"]["alpha"])
    low = study.get_scalar(related["quantiles"][0.05])
    high = study.get_scalar(related["quantiles"][0.95])
    print(f"90 % band at 8 degrees: {low[-1]:.3f} to {high[-1]:.3f}")
```

///

/// tab | MATLAB

```matlab
study = gamut.open('uncertain.gamut');
related = study.related('cl');
fprintf('the std of cl: %s\n', related.std);
fprintf('its 0.05 and 0.95 quantiles: %s %s\n', related.quantiles(0.05), related.quantiles(0.95));
fprintf('its derivative with respect to alpha: %s\n', related.derivatives('alpha'));
low = study.getScalar(related.quantiles(0.05));
high = study.getScalar(related.quantiles(0.95));
fprintf('90 %% band at 8 degrees: %.3f to %.3f\n', low(end), high(end));
study.close();
```

///

/// tab | Julia

```julia
Gamut.open("uncertain.gamut") do study
    related = Gamut.related(study, "cl")
    println("the std of cl: ", related["std"])
    println("its 0.05 and 0.95 quantiles: ", related["quantiles"][0.05], " ", related["quantiles"][0.95])
    println("its derivative with respect to alpha: ", related["derivatives"]["alpha"])
    low = Gamut.get_scalar(study, related["quantiles"][0.05])
    high = Gamut.get_scalar(study, related["quantiles"][0.95])
    @printf("90 %% band at 8 degrees: %.3f to %.3f\n", low[end], high[end])
end
```

///

/// tab | C++

```cpp
study = gamut::open("uncertain.gamut");
const gamut::Related related = study.related("cl");
std::printf("the std of cl: %s\n", related.std_dev.c_str());
std::printf("its 0.05 and 0.95 quantiles: %s %s\n", related.quantiles.at(0.05).c_str(),
            related.quantiles.at(0.95).c_str());
std::printf("its derivative with respect to alpha: %s\n", related.derivatives.at("alpha").c_str());
const std::vector<double> low = study.get_scalar(related.quantiles.at(0.05));
const std::vector<double> high = study.get_scalar(related.quantiles.at(0.95));
std::printf("90 %% band at 8 degrees: %.3f to %.3f\n", low.back(), high.back());
```

///

/// tab | Rust

```rust
let study = gamut::open("uncertain.gamut")?;
let related = study.related("cl")?;
let (q05, q95) = (related.quantile(0.05).unwrap(), related.quantile(0.95).unwrap());
println!("the std of cl: {}", related.std.as_deref().unwrap_or(""));
println!("its 0.05 and 0.95 quantiles: {q05} {q95}");
println!("its derivative with respect to alpha: {}", related.derivatives["alpha"]);
let (low, high) = (study.get_scalar(q05, ..)?, study.get_scalar(q95, ..)?);
println!("90 % band at 8 degrees: {:.3} to {:.3}", low[low.len() - 1], high[high.len() - 1]);
```

///

Each prints:

```text
the std of cl: cl_std
its 0.05 and 0.95 quantiles: cl_p05 cl_p95
its derivative with respect to alpha: dcl_dalpha
90 % band at 8 degrees: 0.837 to 0.923
```

`related` finds everything that describes a result, in every language:
the core reads it from each result's declaration. A plotting script draws
error bars, and a training script collects gradients, without knowing the
names the producer chose.

## Notes

- Fields take the same declarations: a field can have a `std` field, and a
  scalar can have a derivative field with respect to node position.
- A [model file](07-models.md) serves the same relations: a model that
  predicts a spread declares a `std` result exactly as data does.
- A gradient over many parameters is one derivative per parameter.

Run it: `python examples/06_uncertainty_gradients.py`, or `uncertain` from
`examples/matlab`, `examples/julia` and `examples/cpp`
([installing](../install.md) says how to run each). Next:
[models](07-models.md).

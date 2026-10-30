# 5. Time series

A transient run saves its state many times. Each saved step is a row, with
time as a parameter, and a group label says which run each row belongs to.
The steps of one run then read like any other rows, and tools keep them
together: a viewer animates one run, and a model trained on the study is
tested on runs it has not seen rather than on steps between ones it has.

The example is two runs at two speeds, each saved at 101 steps, with a
lift coefficient that oscillates as vortex shedding behind a cylinder
would make it.

## Writing

/// tab | Python

```python
with gamut.create("transient.gamut", writer="example transient",
                   labels={"run": {"role": "group"}},
                   parameters={"t": {"units": "s", "role": "time", "run_group": "run"},
                               "speed": {"units": "m s-1", "role": "condition"}},
                   scalars={"cl": "1"}) as study:
    for name, speed in (("slow", 20.0), ("fast", 35.0)):
        frequency = 0.2 * speed / 10.0                       # shedding, Strouhal 0.2
        cl = 0.8 * np.sin(2 * np.pi * frequency * steps) * (1 - np.exp(-steps))
        study.add_runs({"run": [name] * len(steps), "t": steps,
                        "speed": np.full(len(steps), speed), "cl": cl})
```

///

/// tab | MATLAB

```matlab
study = gamut.create('transient.gamut', 'writer', 'example transient', ...
    'labels', struct('run', struct('role', 'group')), ...
    'parameters', struct('t', struct('units', 's', 'role', 'time', 'runGroup', 'run'), ...
                         'speed', struct('units', 'm s-1', 'role', 'condition')), ...
    'scalars', struct('cl', '1'));
runs = {'slow', 20; 'fast', 35};
for k = 1:size(runs, 1)
    speed = runs{k, 2};
    frequency = 0.2 * speed / 10;                                   % shedding, Strouhal 0.2
    cl = 0.8 * sin(2 * pi * frequency * steps) .* (1 - exp(-steps));
    study.addRuns(struct('run', {repmat(runs(k, 1), numel(steps), 1)}, 't', steps, ...
        'speed', repmat(speed, numel(steps), 1), 'cl', cl));
end
study.close();
```

///

/// tab | Julia

```julia
Gamut.create("transient.gamut"; writer="example transient",
              labels=Dict("run" => (role="group",)),
              parameters=Dict("t" => (units="s", role="time", run_group="run"),
                              "speed" => (units="m s-1", role="condition")),
              scalars=Dict("cl" => "1")) do study
    for (name, speed) in ("slow" => 20.0, "fast" => 35.0)
        frequency = 0.2 * speed / 10.0                              # shedding, Strouhal 0.2
        cl = 0.8 .* sin.(2π * frequency .* steps) .* (1 .- exp.(-steps))
        Gamut.add_runs!(study, Dict("run" => fill(name, length(steps)), "t" => steps,
                                    "speed" => fill(speed, length(steps)), "cl" => cl))
    end
end
```

///

/// tab | C++

```cpp
auto study = gamut::create("transient.gamut", "example transient");
study.declare_label("run", "group");
study.declare_parameter("t", "time", "s", "run");
study.declare_parameter("speed", "condition", "m s-1");
study.declare_scalar("cl", "1");
for (const auto& [name, speed] : std::vector<std::pair<std::string, double>>{{"slow", 20.0}, {"fast", 35.0}}) {
  const double frequency = 0.2 * speed / 10.0;    // shedding, Strouhal 0.2
  std::vector<double> cl;
  for (const double t : steps) cl.push_back(0.8 * std::sin(2 * pi * frequency * t) * (1 - std::exp(-t)));
  study.add_runs({{"run", std::vector<std::string>(steps.size(), name)}, {"t", steps},
                  {"speed", std::vector<double>(steps.size(), speed)}, {"cl", cl}});
}
study.close();
```

///

/// tab | Rust

```rust
let mut study = gamut::create("transient.gamut", "example transient", "", "")?;
study.declare_label("run", "group", &[])?;
study.declare_parameter_with("t", "time", "s", Parameter::default().run_group("run"))?;
study.declare_parameter("speed", "condition", "m s-1")?;
study.declare_scalar("cl", "1")?;
for (name, speed) in [("slow", 20.0), ("fast", 35.0)] {
    let frequency = 0.2 * speed / 10.0;   // shedding, Strouhal 0.2
    let cl: Vec<f64> = steps.iter().map(|t| 0.8 * (2.0 * PI * frequency * t).sin() * (1.0 - (-t).exp())).collect();
    study.add_runs(&[("run", vec![name; steps.len()].into()), ("t", steps.clone().into()),
                     ("speed", vec![speed; steps.len()].into()), ("cl", cl.into())], &[])?;
}
study.close()?;
```

///

- The parameter `t` has the role `time`, and its run group names the
  label that groups its rows into runs.
- The label `run` declares no categories: its table grows as new names
  appear.
- `add_runs` (`addRuns` in MATLAB, `add_runs!` in Julia) adds many rows
  at once, a column per name.

## Reading

/// tab | Python

```python
with gamut.open("transient.gamut") as study:
    print(f"{study.row_count} rows, {len(study.categories('run'))} runs")
    fast = study.select("run == fast")
    t, cl = study.get_parameter("t", rows=fast), study.get_scalar("cl", rows=fast)
    peak = np.abs(cl).argmax()
    print(f"fast run: {len(fast)} steps, peak |cl| {abs(cl[peak]):.2f} at t = {t[peak]:.1f} s")
```

///

/// tab | MATLAB

```matlab
study = gamut.open('transient.gamut');
fprintf('%d rows, %d runs\n', study.rowCount(), numel(study.categories('run')));
fast = study.select('run == fast');
t = study.getParameter('t', 'rows', fast);
cl = study.getScalar('cl', 'rows', fast);
[peak, k] = max(abs(cl));
fprintf('fast run: %d steps, peak |cl| %.2f at t = %.1f s\n', numel(fast), peak, t(k));
study.close();
```

///

/// tab | Julia

```julia
Gamut.open("transient.gamut") do study
    println(study.row_count, " rows, ", length(Gamut.categories(study, "run")), " runs")
    fast = Gamut.select(study, "run == fast")
    t, cl = Gamut.get_parameter(study, "t"; rows=fast), Gamut.get_scalar(study, "cl"; rows=fast)
    peak = argmax(abs.(cl))
    @printf("fast run: %d steps, peak |cl| %.2f at t = %.1f s\n", length(fast), abs(cl[peak]), t[peak])
end
```

///

/// tab | C++

```cpp
study = gamut::open("transient.gamut");
std::printf("%lld rows, %zu runs\n", (long long)study.row_count(), study.categories("run").size());
const auto fast = study.select("run == fast");
const std::vector<double> t = study.get_parameter<double>("t", fast), cl = study.get_scalar("cl", fast);
size_t peak = 0;
for (size_t k = 1; k < cl.size(); ++k)
  if (std::abs(cl[k]) > std::abs(cl[peak])) peak = k;
std::printf("fast run: %zu steps, peak |cl| %.2f at t = %.1f s\n", fast.size(), std::abs(cl[peak]), t[peak]);
```

///

/// tab | Rust

```rust
let study = gamut::open("transient.gamut")?;
println!("{} rows, {} runs", study.row_count()?, study.categories("run")?.len());
let fast = study.select("run == fast")?;
let t: Vec<f64> = study.get_parameter("t", &fast)?;
let cl = study.get_scalar("cl", &fast)?;
let peak = (0..cl.len()).fold(0, |p, k| if cl[k].abs() > cl[p].abs() { k } else { p });
println!("fast run: {} steps, peak |cl| {:.2} at t = {:.1} s", fast.len(), cl[peak].abs(), t[peak]);
```

///

Each prints:

```text
202 rows, 2 runs
fast run: 101 steps, peak |cl| 0.80 at t = 7.5 s
```

A file reports what it holds beyond its type as *add-ons*, which a
study's `addons` lists in Python, MATLAB and Julia: `time` here;
`uncertainty` and `gradients` on the [next page](06-uncertainty-and-gradients.md).

## Notes

- Runs may differ in length and in their save times, and their rows need
  not be contiguous. Two rows of one run at the same time are reported.
- With a mesh, every step brings its fields like any other row. A history
  sampled at the same times in every run is rows too, not a separate case.
- A single transient run needs no group label.

Run it: `python examples/05_time_series.py`, or `transient` from
`examples/matlab`, `examples/julia` and `examples/cpp`
([installing](../install.md) says how to run each). Next:
[uncertainty and gradients](06-uncertainty-and-gradients.md).

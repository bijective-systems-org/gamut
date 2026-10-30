# Gamut documentation

Gamut, by [Bijective Systems](https://github.com/bijective-systems-org), is
an open file format for parametric simulation studies and the models
fitted to them. A `.gamut` file is HDF5 laid out as valid netCDF-4, with
libraries for Python, MATLAB, Julia, C++ and C.

## A study in four languages

A sweep of a wing's angle of attack: six runs written at once, a seventh
added by reopening the file, then the lift of the runs that converged read
back. The
same program in each language; choosing one here shows it in every
example.

/// tab | Python

```python
alpha = np.arange(0.0, 11.0, 2.0)  # six angles of attack, in degrees
cl = 0.11 * alpha                  # stands for the solver's lift coefficients

with gamut.create("sweep.gamut", writer="example sweep",
                   parameters={"alpha": {"units": "degree", "role": "condition"}},
                   labels={"status": {"role": "status",
                                      "categories": ["converged", "failed"]}},
                   scalars={"cl": "1"}) as study:
    study.add_runs({"alpha": alpha, "cl": cl,
                    "status": ["converged"] * len(alpha)})

with gamut.open("sweep.gamut", mode="a") as study:
    study.add_run({"alpha": 12, "status": "failed"})

with gamut.open("sweep.gamut") as study:
    lift = study.get_scalar("cl", rows=study.select("status == converged"))
```

///

/// tab | MATLAB

```matlab
alpha = (0:2:10)';   % six angles of attack, in degrees
cl = 0.11 * alpha;   % stands for the solver's lift coefficients

study = gamut.create('sweep.gamut', 'writer', 'example sweep', ...
    'parameters', struct('alpha', struct('units', 'degree', ...
                                         'role', 'condition')), ...
    'labels', struct('status', struct('role', 'status', ...
                                      'categories', {{'converged', 'failed'}})), ...
    'scalars', struct('cl', '1'));
status = repmat({'converged'}, numel(alpha), 1);
study.addRuns(struct('alpha', alpha, 'cl', cl, 'status', {status}));
study.close();

study = gamut.open('sweep.gamut', 'mode', 'a');
study.addRun(struct('alpha', 12, 'status', 'failed'));
study.close();

study = gamut.open('sweep.gamut');
lift = study.getScalar('cl', 'rows', study.select('status == converged'));
study.close();
```

///

/// tab | Julia

```julia
alpha = collect(0.0:2.0:10.0)  # six angles of attack, in degrees
cl = 0.11 .* alpha             # stands for the solver's lift coefficients

Gamut.create("sweep.gamut"; writer="example sweep",
              parameters=Dict("alpha" => (units="degree", role="condition")),
              labels=Dict("status" => (role="status",
                                       categories=["converged", "failed"])),
              scalars=Dict("cl" => "1")) do study
    status = fill("converged", length(alpha))
    Gamut.add_runs!(study, Dict("alpha" => alpha, "cl" => cl, "status" => status))
end

Gamut.open("sweep.gamut"; mode="a") do study
    Gamut.add_run!(study, Dict("alpha" => 12.0, "status" => "failed"))
end

lift = Gamut.open("sweep.gamut") do study
    Gamut.get_scalar(study, "cl"; rows=Gamut.select(study, "status == converged"))
end
```

///

/// tab | C++

```cpp
const std::vector<double> alpha = {0, 2, 4, 6, 8, 10};  // angles of attack, degrees
std::vector<double> cl;  // stands for the solver's lift coefficients
for (const double a : alpha) cl.push_back(0.11 * a);

auto study = gamut::create("sweep.gamut", "example sweep");
study.declare_parameter("alpha", "condition", "degree");
study.declare_label("status", "status", {"converged", "failed"});
study.declare_scalar("cl", "1");
const std::vector<std::string> status(alpha.size(), "converged");
study.add_runs({{"alpha", alpha}, {"cl", cl}, {"status", status}});
study.close();

study = gamut::open("sweep.gamut", "a");
study.add_run({{"alpha", 12.0}, {"status", "failed"}});
study.close();

study = gamut::open("sweep.gamut");
const std::vector<double> lift =
    study.get_scalar("cl", study.select("status == converged"));
```

///

Each prints:

```text
lift of the runs that converged: 0.00 0.22 0.44 0.66 0.88 1.10
```

## Where next

- [Installing](install.md): each language, and the platforms the
  packages are built for.
- [How it works](concepts/README.md): what a file holds, and why it is
  shaped as it is.
- [Examples](guide/README.md): a study built up one idea at a time, from
  a table of runs to meshes, models and VTK, in each language.
- [Reference](reference/python.md): each language's calls, the command
  line and the [specification](reference/specification.md), which defines
  the format.

For coding agents,
[llms.txt](https://raw.githubusercontent.com/bijective-systems-org/gamut/main/llms.txt)
collects the API's patterns and plain-text links to these pages. To cite
Gamut, use its [citation metadata](https://github.com/bijective-systems-org/gamut/blob/main/CITATION.cff).

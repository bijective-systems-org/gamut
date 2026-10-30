# Gamut documentation

Gamut, by [Bijective Systems](https://github.com/bijective-systems-org), is
an open file format for parametric simulation studies and the models
fitted to them. A `.gamut` file is HDF5 laid out as valid netCDF-4, with
libraries for Python, MATLAB, Julia, C++ and C.

The Python distribution on [PyPI](https://pypi.org/project/gamut-format/)
is **gamut-format**: install `gamut-format`, then `import gamut`.
The command line is `gamut`. The PyPI project named `gamut` is a different
package. [Installing](install.md) covers each language and platform.

## A study in four languages

A sweep of a wing's angle of attack: six runs written, a seventh added by
reopening the file, then the lift of the runs that converged read back. The
same program in each language; choosing one here shows it in every
example.

/// tab | Python

```python
with gamut.create("sweep.gamut", writer="example sweep",
                   parameters={"alpha": {"units": "degree", "role": "condition"}},
                   labels={"status": {"role": "status", "categories": ["converged", "failed"]}},
                   scalars={"cl": "1"}) as study:
    for alpha in range(0, 11, 2):
        study.add_run({"alpha": alpha, "status": "converged", "cl": solve(alpha)})

with gamut.open("sweep.gamut", mode="a") as study:
    study.add_run({"alpha": 12, "status": "failed"})

with gamut.open("sweep.gamut") as study:
    cl = study.get_scalar("cl", rows=study.select("status == converged"))
```

///

/// tab | MATLAB

```matlab
study = gamut.create('sweep.gamut', 'writer', 'example sweep', ...
    'parameters', struct('alpha', struct('units', 'degree', 'role', 'condition')), ...
    'labels', struct('status', struct('role', 'status', 'categories', {{'converged', 'failed'}})), ...
    'scalars', struct('cl', '1'));
for alpha = 0:2:10
    study.addRun(struct('alpha', alpha, 'status', 'converged', 'cl', solve(alpha)));
end
study.close();

study = gamut.open('sweep.gamut', 'mode', 'a');
study.addRun(struct('alpha', 12, 'status', 'failed'));
study.close();

study = gamut.open('sweep.gamut');
cl = study.getScalar('cl', 'rows', study.select('status == converged'));
study.close();
```

///

/// tab | Julia

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

///

/// tab | C++

```cpp
auto study = gamut::create("sweep.gamut", "example sweep");
study.declare_parameter("alpha", "condition", "degree");
study.declare_label("status", "status", {"converged", "failed"});
study.declare_scalar("cl", "1");
for (double alpha = 0.0; alpha <= 10.0; alpha += 2.0)
  study.add_run({{"alpha", alpha}, {"status", "converged"}, {"cl", solve(alpha)}});
study.close();

study = gamut::open("sweep.gamut", "a");
study.add_run({{"alpha", 12.0}, {"status", "failed"}});
study.close();

study = gamut::open("sweep.gamut");
const std::vector<double> cl = study.get_scalar("cl", study.select("status == converged"));
```

///

Each prints:

```text
lift of the runs that converged: 0.00 0.22 0.44 0.66 0.88 1.10
```

## Where next

[Installing](install.md) covers each language and platform.
[How it works](concepts/README.md) explains what a file holds and why it
is shaped as it is. The [examples](guide/README.md) build a study up one
idea at a time, from a table of runs to meshes, models and VTK, each a
program that runs as shown. The [reference](reference/command-line.md)
has the command line, each language's spelling of the calls, and the
[specification](https://github.com/bijective-systems-org/gamut/blob/main/SPEC.md),
which defines the format.

For coding agents,
[llms.txt](https://raw.githubusercontent.com/bijective-systems-org/gamut/main/llms.txt)
collects the API's patterns and plain-text links to these pages. To cite
Gamut, use its [citation metadata](https://github.com/bijective-systems-org/gamut/blob/main/CITATION.cff).

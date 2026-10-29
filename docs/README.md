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
same program in each language; choose one and every example on this site
follows.

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

Each prints

```text
lift of the runs that converged: 0.00 0.22 0.44 0.66 0.88 1.10
```

## Start with a study

- [Overview and examples](../README.md): write, append and read a study in four languages.
- [Guide](guide/README.md): one concept per page, quoting runnable programs in [examples](../examples).
- [Run tables](guide/01-run-tables.md): inputs, status and results with units.
- [Shared meshes](guide/02-one-mesh.md): fields as runs by nodes or cells.
- [Fitted models](guide/07-models.md): store a model's numbers and evaluate new inputs.
- [Command line](guide/11-command-line.md): inspect, validate, build and extract files.

## Reference and interoperability

- [File format specification](../SPEC.md): the authoritative layout, meaning, validation rules and format versions.
- [Selecting rows](reference/selecting.md): the query grammar.
- [C API](../include/gamut/gamut.h) and [C++ API](../include/gamut/gamut.hpp): public headers.
- [Python API](../python/gamut/__init__.py): public functions and docstrings, also available through `help(gamut)`.
- [Conformance corpus](../corpus): valid, invalid and hostile files with expected outcomes.
- [Files from outside](security.md): validation and process boundaries for untrusted files.
- [Comparison](comparison.md) and [benchmarks](benchmarks.md): scope, trade-offs and measured workloads.

The package version and file format version are separate: a file declares
`gamut/1`. [The specification's version rules](../SPEC.md#17-versions-and-additions)
define compatibility. [Release history](../CHANGELOG.md) describes package changes.

## Plain-text entry points

[llms.txt](https://raw.githubusercontent.com/bijective-systems-org/gamut/main/llms.txt)
collects API patterns and raw documentation links for coding agents.
The [raw specification](https://raw.githubusercontent.com/bijective-systems-org/gamut/main/SPEC.md)
defines the format; the [citation metadata](../CITATION.cff) identifies the software.
The canonical source and documentation live in the
[Gamut repository](https://github.com/bijective-systems-org/gamut).

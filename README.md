<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/bijective-systems-org/gamut/main/docs/assets/logo-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/bijective-systems-org/gamut/main/docs/assets/logo.svg">
    <img src="https://raw.githubusercontent.com/bijective-systems-org/gamut/main/docs/assets/logo-any.svg" alt="Gamut" width="240">
  </picture>
</p>

# Gamut: an open file format for parametric simulation studies

By [Bijective Systems](https://github.com/bijective-systems-org), with
libraries for Python, MATLAB, Julia, C++ and C.

[Documentation](https://bijective-systems-org.github.io/gamut/) ·
[Installing](https://bijective-systems-org.github.io/gamut/install.html) ·
[Examples](https://bijective-systems-org.github.io/gamut/guide/index.html) ·
[Specification](https://bijective-systems-org.github.io/gamut/reference/specification.html) ·
[PyPI: gamut-format](https://pypi.org/project/gamut-format/) ·
[Releases](https://github.com/bijective-systems-org/gamut/releases)

<p align="center">
  <a href="https://github.com/bijective-systems-org/gamut/actions/workflows/ci.yml"><img src="https://github.com/bijective-systems-org/gamut/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI"></a>
</p>

---

Gamut is a file format for parametric simulation studies: the hundreds or
thousands of CFD or FEA runs behind a design sweep, an aerodynamic
database or a surrogate model. One file holds the run table, each run's
inputs, results and status, and, when the runs have a mesh, the mesh and
every field on it, all with units. A model fitted to the runs is saved the
same way, as plain numbers with no code. Every language reads and writes
the file through one core, so each reads what another wrote, value for
value.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/bijective-systems-org/gamut/main/docs/assets/languages-dark.svg">
    <img src="https://raw.githubusercontent.com/bijective-systems-org/gamut/main/docs/assets/languages.svg" alt="Python (with the command line), MATLAB, Julia, C++ and C each read and write a .gamut file through the C interface of the one C++ core; Rust and Fortran are planned." width="760">
  </picture>
</p>

## Example

A sweep of a wing's angle of attack: six runs written at once, a seventh
added later, and the lift of the runs that converged read back. `cl`
stands for your solver's results.

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

<details>
<summary>MATLAB</summary>

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

</details>

<details>
<summary>Julia</summary>

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

</details>

<details>
<summary>C++</summary>

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

</details>

All four print the same line:

```text
lift of the runs that converged: 0.00 0.22 0.44 0.66 0.88 1.10
```

The [examples](https://bijective-systems-org.github.io/gamut/guide/index.html) go on from here, a step at a time
and in each language: a mesh shared by every run, families of shapes,
meshes that change, time series, uncertainty, and models fitted to the
runs.

## Performance

<p align="center">
  <img src="https://raw.githubusercontent.com/bijective-systems-org/gamut/main/docs/assets/bench-study.svg" alt="File size and read times of Exodus II, CGNS and PhysicsNeMo-Mesh relative to Gamut, for a triangulated capsule geometry family and an XFOIL airfoil sweep. Every format uses the same mesh within each dataset." width="760">
</p>

On the triangulated capsule family, Gamut and compressed Exodus occupy
about the same space, and Gamut is smaller and reads one run faster than
PhysicsNeMo-Mesh, which writes faster; on the smaller airfoil sweep,
PhysicsNeMo-Mesh reads faster and Gamut is smaller. PhysicsNeMo-Mesh needs
triangles, so every format here uses the capsule converted to triangles.
The [benchmarks](https://bijective-systems-org.github.io/gamut/benchmarks.html) give the full timings, settings
and machine, the original quadrilateral results, and the workloads where
another approach is faster.

## Install

| Language | Install |
|---|---|
| Python 3.11 or later | `pip install gamut-format` |
| MATLAB R2023b or later | open `Gamut.mltbx` from the [latest release](https://github.com/bijective-systems-org/gamut/releases/latest) |
| Julia 1.10 or later | `Pkg.add(url="https://github.com/bijective-systems-org/gamut", subdir="julia", rev="v2.0.0")` |
| C++ and C | CMake build and install, then `find_package(gamut)`; include `gamut/gamut.hpp` (C++17) or `gamut/gamut.h` (C) |

In Python, install `gamut-format`, then `import gamut`; the PyPI project
named `gamut` is a different package. [Installing](https://bijective-systems-org.github.io/gamut/install.html) has
the details for each language, and [llms.txt](https://raw.githubusercontent.com/bijective-systems-org/gamut/main/llms.txt) gives coding
agents a plain-text overview.

## License

[Apache 2.0](https://github.com/bijective-systems-org/gamut/blob/main/LICENSE). Made by [Bijective Systems](https://github.com/bijective-systems-org).
If you use Gamut in published work, please cite it ([CITATION.cff](https://github.com/bijective-systems-org/gamut/blob/main/CITATION.cff)).

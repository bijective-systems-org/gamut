# First file

Already have a `.gamut` file? [Check what's inside](#inspect-and-validate)
or read one of its columns with `open` and `get_scalar`, as shown below.

## Write and read three runs

Each row records one run. Angle of attack (`alpha`) is the input.
Lift coefficient (`cl`) is the result.

| `alpha` (degrees) | `cl` (dimensionless) |
|---:|---:|
| 0 | 0.00 |
| 2 | 0.22 |
| 4 | 0.44 |

Declare the column names and units when you create the file. The input
has role `condition` because it describes how the wing was tested.
A *scalar* stores one result per run. Use `1` for a dimensionless value.

Run the example in a directory without a `first.gamut` file. It writes
the two columns, closes the file, then reopens it and reads all of `cl`.

/// tab | Python

In an activated Python 3.11 or later virtual environment, install Gamut.

```bash
python -m pip install bijective-gamut
```

Save the code below as `sweep.py` and run `python sweep.py`.

[Source](https://github.com/bijective-systems-org/gamut/blob/main/examples/00_readme.py)

```python
import gamut

# Values at the same position belong to the same run.
alpha = [0.0, 2.0, 4.0]
cl = [0.0, 0.22, 0.44]

with gamut.create(
    "first.gamut",
    writer="example sweep",
    parameters={"alpha": {"units": "degree", "role": "condition"}},
    scalars={"cl": "1"},
) as study:
    study.add_runs({"alpha": alpha, "cl": cl})

with gamut.open("first.gamut") as study:
    lift = study.get_scalar("cl")

print("cl:", " ".join(f"{value:.2f}" for value in lift))
```

///

/// tab | MATLAB

[Install for MATLAB](install.md).

[Source](https://github.com/bijective-systems-org/gamut/blob/main/examples/matlab/sweep.m)

```matlab
% Values at the same position belong to the same run.
alpha = [0; 2; 4];
cl = [0; 0.22; 0.44];

study = gamut.create('first.gamut', 'writer', 'example sweep', ...
    'parameters', struct('alpha', struct('units', 'degree', 'role', 'condition')), ...
    'scalars', struct('cl', '1'));
study.addRuns(struct('alpha', alpha, 'cl', cl));
study.close();

study = gamut.open('first.gamut');
lift = study.getScalar('cl');
study.close();

fprintf('cl: %s\n', strjoin(compose('%.2f', lift), ' '));
```

///

/// tab | Julia

[Install for Julia](install.md).

[Source](https://github.com/bijective-systems-org/gamut/blob/main/examples/julia/sweep.jl)

```julia
using GamutFile
using Printf

# Values at the same position belong to the same run.
alpha = [0.0, 2.0, 4.0]
cl = [0.0, 0.22, 0.44]

GamutFile.create("first.gamut"; writer="example sweep",
                 parameters=Dict("alpha" => (units="degree", role="condition")),
                 scalars=Dict("cl" => "1")) do study
    GamutFile.add_runs!(study, Dict("alpha" => alpha, "cl" => cl))
end

lift = GamutFile.open("first.gamut") do study
    GamutFile.get_scalar(study, "cl")
end

println("cl: ", join([@sprintf("%.2f", value) for value in lift], " "))
```

///

/// tab | C++

[Install for C++](install.md).

[Source](https://github.com/bijective-systems-org/gamut/blob/main/examples/cpp/sweep.cpp)

```cpp
#include <cstdio>
#include <vector>

#include <gamut/gamut.hpp>

int main() {
  // Values at the same position belong to the same run.
  const std::vector<double> alpha = {0, 2, 4};
  const std::vector<double> cl = {0, 0.22, 0.44};

  auto study = gamut::create("first.gamut", "example sweep");
  study.declare_parameter("alpha", "condition", "degree");
  study.declare_scalar("cl", "1");
  study.add_runs({{"alpha", alpha}, {"cl", cl}});
  study.close();

  study = gamut::open("first.gamut");
  const auto lift = study.get_scalar("cl");

  std::printf("cl:");
  for (const double value : lift) std::printf(" %.2f", value);
  std::printf("\n");
}
```

///

/// tab | Rust

[Install for Rust](install.md).

[Source](https://github.com/bijective-systems-org/gamut/blob/main/examples/rust/sweep.rs)

```rust
fn main() -> Result<(), gamut::Error> {
    // Values at the same position belong to the same run.
    let alpha = vec![0.0, 2.0, 4.0];
    let cl = vec![0.0, 0.22, 0.44];

    let mut study = gamut::create("first.gamut", "example sweep", "", "")?;
    study.declare_parameter("alpha", "condition", "degree")?;
    study.declare_scalar("cl", "1")?;
    study.add_runs(&[("alpha", alpha.into()), ("cl", cl.into())], &[])?;
    study.close()?;

    let study = gamut::open("first.gamut")?;
    let lift = study.get_scalar("cl", gamut::Selection::All)?;

    print!("cl:");
    for value in lift {
        print!(" {value:.2}");
    }
    println!();
    Ok(())
}
```

///

The program prints one lift coefficient per run, in order.

```text
cl: 0.00 0.22 0.44
```

## Inspect and validate

The command line comes with `python -m pip install bijective-gamut`.
For a file someone sent you, substitute its path.

```console
$ gamut info first.gamut
first.gamut: table, 3 runs
  parameters  alpha [degree] 0 to 4
  results     cl [1]
  file        ... KB
$ gamut validate first.gamut
no errors, no warnings
```

Use a name from the `results` line, such as `cl`, in the scalar read above.
`validate` checks the file against the format rules.

[Next: store and read run status](guide/01-run-tables.md)

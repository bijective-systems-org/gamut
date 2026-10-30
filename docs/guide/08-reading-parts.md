# 8. Reading parts

A study file can be much larger than memory. Reads name what they want:
runs by a condition, and nodes or cells by position or by zone.

The example writes pressure on the cylinder of
[one mesh](02-one-mesh.md) at three speeds and three circulations, then
reads the wall pressure of some of the runs, in kilopascals.

## Reading

/// tab | Python

```python
with gamut.open("parts.gamut") as study:
    rows = study.select("speed >= 20 and gamma > 1 and status == converged")
    print("chosen:", len(rows), "runs")
    wall = study.categories("surface").index("wall")
    on_wall = np.flatnonzero(study.get_mesh_label("surface") == wall)
    p_wall = study.get_field("p", rows=rows, nodes=on_wall, units="kPa")
    print(f"wall pressure: {p_wall.shape[0]} runs x {p_wall.shape[1]} nodes, lowest {p_wall.min():.3f} kPa")
    speeds = study.get_parameter("speed", rows=rows, units="km/h")
    print("speeds in km/h:", " ".join(f"{v:.1f}" for v in speeds))
```

///

/// tab | MATLAB

```matlab
study = gamut.open('parts.gamut');
rows = study.select('speed >= 20 and gamma > 1 and status == converged');
fprintf('chosen: %d runs\n', numel(rows));
wall = find(strcmp(study.categories('surface'), 'wall')) - 1;    % the code that means 'wall'
onWall = find(study.getMeshLabel('surface') == wall);
pWall = study.getField('p', 'rows', rows, 'nodes', onWall) / 1000;   % stored in Pa; kPa
fprintf('wall pressure: %d runs x %d nodes, lowest %.3f kPa\n', size(pWall, 1), size(pWall, 2), min(pWall(:)));
speeds = study.getParameter('speed', 'rows', rows) * 3.6;            % stored in m s-1; km/h
fprintf('speeds in km/h:%s\n', sprintf(' %.1f', speeds));
study.close();
```

///

/// tab | Julia

```julia
Gamut.open("parts.gamut") do study
    rows = Gamut.select(study, "speed >= 20 and gamma > 1 and status == converged")
    println("chosen: ", length(rows), " runs")
    wall = findfirst(==("wall"), Gamut.categories(study, "surface")) - 1   # the code that means "wall"
    on_wall = findall(==(wall), vec(Gamut.get_mesh_label(study, "surface")))
    p_wall = Gamut.get_field(study, "p"; rows, nodes=on_wall) ./ 1000      # stored in Pa; kPa
    @printf("wall pressure: %d runs x %d nodes, lowest %.3f kPa\n", size(p_wall)..., minimum(p_wall))
    speeds = Gamut.get_parameter(study, "speed"; rows) .* 3.6               # stored in m s-1; km/h
    println("speeds in km/h: ", join((@sprintf("%.1f", v) for v in speeds), " "))
end
```

///

/// tab | C++

```cpp
study = gamut::open("parts.gamut");
const auto rows = study.select("speed >= 20 and gamma > 1 and status == converged");
std::printf("chosen: %zu runs\n", rows.size());
const auto names = study.categories("surface");
const int64_t wall = std::find(names.begin(), names.end(), "wall") - names.begin();
std::vector<int64_t> on_wall;
const auto label = study.get_mesh_label("surface");
for (int64_t k = 0; k < int64_t(label.size()); ++k)
  if (label[size_t(k)] == wall) on_wall.push_back(k);
const auto p_wall = study.get_field("p", rows, on_wall);  // stored in Pa
const double lowest = *std::min_element(p_wall.values.begin(), p_wall.values.end()) / 1000;
std::printf("wall pressure: %lld runs x %lld nodes, lowest %.3f kPa\n", (long long)p_wall.shape[0],
            (long long)p_wall.shape[1], lowest);
std::printf("speeds in km/h:");
for (const double v : study.get_parameter<double>("speed", rows)) std::printf(" %.1f", v * 3.6);  // stored in m s-1
std::printf("\n");
```

///

/// tab | Rust

```rust
let study = gamut::open("parts.gamut")?;
let rows = study.select("speed >= 20 and gamma > 1 and status == converged")?;
println!("chosen: {} runs", rows.len());
let names = study.categories("surface")?;
let wall = names.iter().position(|n| n == "wall").unwrap() as i64;
let label = study.get_mesh_label("surface", None)?;
let on_wall: Vec<usize> = (0..label.len()).filter(|&k| label[k] == wall).collect();
let p_wall = study.get_field("p", &rows, on_wall)?;   // stored in Pa
let lowest = p_wall.values.iter().copied().fold(f64::INFINITY, f64::min) / 1000.0;
println!("wall pressure: {} runs x {} nodes, lowest {lowest:.3} kPa", p_wall.shape[0], p_wall.shape[1]);
let speeds: Vec<f64> = study.get_parameter("speed", &rows)?;   // stored in m s-1
println!("speeds in km/h:{}", speeds.iter().map(|v| format!(" {:.1}", v * 3.6)).collect::<String>());
```

///

Each prints:

```text
chosen: 4 runs
wall pressure: 4 runs x 48 nodes, lowest -5.833 kPa
speeds in km/h: 72.0 72.0 144.0 144.0
```

### Runs

`select` compares parameters, scalars and labels with `==`, `!=`,
`<`, `<=`, `>`, `>=`, joined by `and`, `or`, `not` and parentheses. A
label compares by name, with quotes when the name has spaces:
`model == "k-omega SST"`. The [reference](../reference/selecting.md) has
the whole grammar. Any list of positions works as rows too, so a
selection can come from the program just as well.

### Nodes and cells

Reads take nodes or cells as positions: one, a list, or every one when
left out. A zone comes from a mesh label: `categories` gives its names,
and the positions where the label holds a name's code are that zone. The
codes count from 0 in every language, so a name's code is its place in
`categories` less one in MATLAB and Julia.

### Units

Values are stored in the units they were written in, which
`describe(name)` names. In Python, every read takes `units` and converts
from the stored units; this needs the `units` extra
(`pip install "bijective-gamut[units]"`, which brings pint), and without it
a read that asks for other units is refused. MATLAB, Julia, C++ and Rust
return the stored units, and the programs above convert them.

## Notes

- In Python, writing converts too: a value given as `(number, "units")`
  in `add_run` is converted to the declared units before it is stored.
- Opening a file with four threads (`threads=4` in Python and Julia,
  `'threads', 4` in MATLAB, `gamut::open(path, "r", 4)` in C++,
  `study.set_threads(4)` in Rust)
  decompresses large field reads in four threads, with the same result as
  one.
- Studies can be opened and read from several threads at once. Their calls
  take turns, because HDF5 holds state for the whole process; threads at
  opening are what make one large read faster.
- Opening a file reads its structure and attributes only. Nothing else is
  read until it is asked for.

Run it: `python examples/08_selecting_parts.py`, or `parts` from
`examples/matlab`, `examples/julia` and `examples/cpp`
([installing](../install.md) says how to run each). Next:
[combining files](09-combining-files.md).

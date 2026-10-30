# 3. Geometry families

A design study often runs several shapes, each at several conditions. When
the shapes are meshed with one topology, node k is the same place on every
shape (a correspondence, which a mapping or morphing tool builds for real
geometry), so fields compare node by node across the whole family. The
file keeps one mesh, stores each member's coordinates once, and keeps
every field as one block of runs × nodes.

The example is three cylinders of different radius, each run at three
circulations. `ring` and `pressure` stand for the mesher and the solver:
they build the ring of quadrilaterals around a cylinder and the pressure
coefficient of the flow past it, and are beside each program in
`examples/`.

## Writing

/// tab | Python

```python
with gamut.create("family.gamut", writer="example family", mesh="shared", per="group:member",
                   coordinates={"units": "m", "axes": 2},
                   labels={"member": {"role": "group", "categories": list(members)},
                           "split": {"role": "split", "categories": ["train", "test"]}},
                   generalisation_group="member",
                   parameters={"gamma": {"units": "m2 s-1", "role": "condition"}},
                   fields={"cp": {"units": "1", "at": "node"}}) as study:
    study.set_mesh(cells=cells, n_nodes=len(ring()[0]))
    for name, radius in members.items():
        points, _, t, r = ring(radius=radius)
        for gamma in (0.0, 2.0, 4.0):
            study.add_run({"member": name, "gamma": gamma,
                           "split": "test" if name == "wide" else "train"},
                          fields={"cp": pressure(t, r, radius, gamma)}, points=points)
```

///

/// tab | MATLAB

```matlab
study = gamut.create('family.gamut', 'writer', 'example family', 'mesh', 'shared', 'per', 'group:member', ...
    'coordinates', struct('units', 'm', 'axes', 2), ...
    'labels', struct('member', struct('role', 'group', 'categories', {names}), ...
                     'split', struct('role', 'split', 'categories', {{'train', 'test'}})), ...
    'generalisationGroup', 'member', ...
    'parameters', struct('gamma', struct('units', 'm2 s-1', 'role', 'condition')), ...
    'fields', struct('cp', struct('units', '1', 'at', 'node')));
study.setMesh([], cells, struct(), size(base, 1));
for k = 1:numel(names)
    [points, ~, t, r] = cylinderRing(radii(k));
    for gamma = [0 2 4]
        split = 'train';
        if strcmp(names{k}, 'wide'), split = 'test'; end
        study.addRun(struct('member', names{k}, 'gamma', gamma, 'split', split), ...
            'fields', struct('cp', cylinderPressure(t, r, radii(k), gamma)), 'points', points);
    end
end
study.close();
```

///

/// tab | Julia

```julia
Gamut.create("family.gamut"; writer="example family", mesh="shared", per="group:member",
              coordinates=(units="m", axes=2),
              labels=Dict("member" => (role="group", categories=first.(members)),
                          "split" => (role="split", categories=["train", "test"])),
              generalisation_group="member",
              parameters=Dict("gamma" => (units="m2 s-1", role="condition")),
              fields=Dict("cp" => (units="1", at="node"))) do study
    Gamut.set_mesh!(study; cells, n_nodes=size(base, 1))
    for (name, radius) in members
        points, _, t, r = ring(; radius)
        for gamma in (0.0, 2.0, 4.0)
            Gamut.add_run!(study, Dict("member" => name, "gamma" => gamma,
                                       "split" => name == "wide" ? "test" : "train");
                           fields=Dict("cp" => pressure(t, r; radius, gamma)), points)
        end
    end
end
```

///

/// tab | C++

```cpp
auto study = gamut::create("family.gamut", "example family", "shared", "group:member");
study.declare_coordinates("m", 2);
study.declare_label("member", "group", {"slim", "base", "wide"});
study.declare_label("split", "split", {"train", "test"});
study.set_generalisation_group("member");
study.declare_parameter("gamma", "condition", "m2 s-1");
study.declare_field("cp", "node", "1");
study.set_mesh(int64_t(base.t.size()), base.cells);
for (const auto& [name, radius] : members) {
  const Ring member = ring(48, 12, radius);
  for (const double gamma : {0.0, 2.0, 4.0}) {
    study.add_run({{"member", name}, {"gamma", gamma}, {"split", name == "wide" ? "test" : "train"}},
                  {{"cp", pressure(member.t, member.r, radius, gamma)}}, gamut::Geometry{member.points, std::nullopt, {}});
  }
}
study.close();
```

///

/// tab | Rust

```rust
let mut study = gamut::create("family.gamut", "example family", "shared", "group:member")?;
study.declare_coordinates("m", 2)?;
study.declare_label("member", "group", &["slim", "base", "wide"])?;
study.declare_label("split", "split", &["train", "test"])?;
study.set_generalisation_group("member")?;
study.declare_parameter("gamma", "condition", "m2 s-1")?;
study.declare_field("cp", "node", "1")?;
study.set_mesh_nodes(base.t.len(), &base.cells, &[])?;
for (name, radius) in members {
    let member = ring(48, 12, radius);
    for gamma in [0.0, 2.0, 4.0] {
        let split = if name == "wide" { "test" } else { "train" };
        study.add_run_with_geometry(&[("member", name.into()), ("gamma", gamma.into()), ("split", split.into())],
                                    &[("cp", &pressure(&member.t, &member.r, radius, gamma))],
                                    &gamut::Geometry { points: &member.points, ..Default::default() })?;
    }
}
study.close()?;
```

///

- The mesh is `per` `group:member`: the geometry changes from one member
  of the `member` label to the next, and is the same for every run of a
  member. The label's role is `group`: rows that belong together.
- The mesh is set once with the cells and the node count; the
  coordinates come with the runs.
- Each run of a member may pass its points; the first sets the member's
  geometry, and a later one must be the same (a different geometry for
  the same member is refused).
- A label with the role `split` publishes which runs are for training and
  which for testing, so everyone who uses the file tests the same way.
  Here the wide cylinder is held out whole.
- The generalisation group, `member`, records that a fair test of a model
  trained on this study holds out whole members. A published split that
  puts runs of one member on both sides is reported (W1).

## Reading

/// tab | Python

```python
with gamut.open("family.gamut") as study:
    print(study.row_count, "runs on", len(members), "members of one topology")
    for name in members:
        first = study.select(f"member == {name}")[0]
        print(f"  {name}: first node at x = {study.get_points(row=first)[0, 0]:.2f} m")
    cp = study.get_field("cp", nodes=[0]).ravel()
    print("cp at the first node, run by run:", " ".join(f"{v:.2f}" for v in cp))
    test = study.select("split == test")
    print("held out for testing:", len(test), "runs of", ", ".join(sorted(set(study.get_label("member", rows=test)))))
```

///

/// tab | MATLAB

```matlab
study = gamut.open('family.gamut');
fprintf('%d runs on %d members of one topology\n', study.rowCount(), numel(names));
for k = 1:numel(names)
    rows = study.select(sprintf('member == %s', names{k}));
    points = study.getPoints(rows(1));
    fprintf('  %s: first node at x = %.2f m\n', names{k}, points(1, 1));
end
cp = study.getField('cp', 'nodes', 1);
fprintf('cp at the first node, run by run:%s\n', sprintf(' %.2f', cp));
test = study.select('split == test');
fprintf('held out for testing: %d runs of %s\n', numel(test), ...
    strjoin(unique(study.getLabel('member', 'rows', test)), ', '));
study.close();
```

///

/// tab | Julia

```julia
Gamut.open("family.gamut") do study
    println(study.row_count, " runs on ", length(members), " members of one topology")
    for (name, _) in members
        row = Gamut.select(study, "member == $name")[1]
        @printf("  %s: first node at x = %.2f m\n", name, Gamut.get_points(study; row)[1, 1])
    end
    cp = Gamut.get_field(study, "cp"; nodes=[1])
    println("cp at the first node, run by run: ", join((@sprintf("%.2f", v) for v in cp), " "))
    test = Gamut.select(study, "split == test")
    println("held out for testing: ", length(test), " runs of ",
            join(unique(Gamut.get_label(study, "member"; rows=test)), ", "))
end
```

///

/// tab | C++

```cpp
study = gamut::open("family.gamut");
std::printf("%lld runs on %zu members of one topology\n", (long long)study.row_count(), members.size());
for (const auto& [name, radius] : members) {
  const int64_t first = study.select("member == " + name)[0];
  std::printf("  %s: first node at x = %.2f m\n", name.c_str(), study.get_points(first)(0, 0));
}
std::printf("cp at the first node, run by run:");
for (const double v : study.get_field("cp", gamut::all, {0})) std::printf(" %.2f", v);
std::printf("\n");
const auto test = study.select("split == test");
const auto held = study.get_label("member", test);
std::string names;
for (const auto& name : std::set<std::string>(held.begin(), held.end())) names += (names.empty() ? "" : ", ") + name;
std::printf("held out for testing: %zu runs of %s\n", test.size(), names.c_str());
```

///

/// tab | Rust

```rust
let study = gamut::open("family.gamut")?;
println!("{} runs on {} members of one topology", study.row_count()?, members.len());
for (name, _) in members {
    let first = study.select(&format!("member == {name}"))?[0];
    println!("  {name}: first node at x = {:.2} m", study.get_points(Some(first))?[[0, 0]]);
}
let first_node = study.get_field("cp", .., 0)?;
println!("cp at the first node, run by run:{}",
         first_node.values.iter().map(|v| format!(" {v:.2}")).collect::<String>());
let test = study.select("split == test")?;
let held: BTreeSet<String> = study.get_label("member", &test)?.into_iter().collect();
println!("held out for testing: {} runs of {}", test.len(), held.into_iter().collect::<Vec<_>>().join(", "));
```

///

Each prints:

```text
9 runs on 3 members of one topology
  slim: first node at x = 0.80 m
  base: first node at x = 1.00 m
  wide: first node at x = 1.20 m
cp at the first node, run by run: 1.00 0.84 0.37 1.00 0.90 0.59 1.00 0.93 0.72
held out for testing: 3 runs of wide
```

Asked for one run, `get_points` returns the geometry that run used,
whatever the mesh's `per`. The first node sits on each cylinder's wall
where the flow stops when there is no circulation, so its pressure
coefficient is 1 there on every member, and falls by less on the larger
cylinders as circulation grows.

## Notes

- `per` `run` is the same idea with a geometry per run: a mesh that
  deforms with every run, such as an aeroelastic or optimisation history.
- Coordinates are always absolute positions, never displacements.
- When the members are meshed separately, with different node counts or
  connectivity, the study is a [changing mesh](04-changing-meshes.md)
  instead, and fields no longer compare node by node.

Run it: `python examples/03_geometry_family.py`, or `family` from
`examples/matlab`, `examples/julia` and `examples/cpp`
([installing](../install.md) says how to run each). Next:
[changing meshes](04-changing-meshes.md).

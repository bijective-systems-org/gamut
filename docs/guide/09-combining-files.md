# 9. Combining files

Studies grow: a second batch of runs on another day, a few failed runs
repeated. Three calls move runs between files, and each checks everything
before it writes the first row, so a refused call adds no
row and changes no run in either file.

| Call | Does |
|---|---|
| `append(dst, src)` | adds `src`'s runs to `dst` in place |
| `extract(src, dst, rows)` | writes chosen runs of `src` as a new file |
| `write_copy(src, dst)` | rewrites a file with the default layout |

MATLAB spells them `gamut.append`, `gamut.extract` and `gamut.writeCopy`,
Julia `GamutFile.append!`, `GamutFile.extract` and `GamutFile.write_copy`, and C++
and Rust `gamut::append`, `gamut::extract` and `gamut::write_copy`. Row ids are the
file's own and count from 0 in every language.

The example writes two days of a Mach sweep, appends the second to the
first, keeps the converged runs, and rewrites that file.

/// tab | Python

```python
sweep("monday.gamut", [0.5, 0.6, 0.7])
sweep("tuesday.gamut", [0.8, 0.9])
print("appended", gamut.append("monday.gamut", "tuesday.gamut"), "runs")

with gamut.open("monday.gamut") as study:
    good = study.select("status == converged")
gamut.extract("monday.gamut", "converged.gamut", good)
gamut.write_copy("converged.gamut", "converged_copy.gamut")

with gamut.open("converged.gamut") as study, gamut.open("converged_copy.gamut") as copy:
    print("kept ids:", *study.get_row_ids(), "at mach", *(f"{m:g}" for m in study.get_parameter("mach")))
    same = study.describe()["file_id"] == copy.describe()["file_id"]
    print("same file id after the rewrite:", "yes" if same else "no")
print("valid:", "yes" if gamut.validate("converged.gamut").ok else "no")
```

///

/// tab | MATLAB

```matlab
sweep('monday.gamut', [0.5 0.6 0.7]);
sweep('tuesday.gamut', [0.8 0.9]);
fprintf('appended %d runs\n', gamut.append('monday.gamut', 'tuesday.gamut'));

study = gamut.open('monday.gamut');
good = study.select('status == converged');
study.close();
gamut.extract('monday.gamut', 'converged.gamut', good);
gamut.writeCopy('converged.gamut', 'converged_copy.gamut');

study = gamut.open('converged.gamut');
copy = gamut.open('converged_copy.gamut');
fprintf('kept ids:%s at mach%s\n', sprintf(' %d', study.getRowIds()), sprintf(' %g', study.getParameter('mach')));
answers = {'no', 'yes'};
fprintf('same file id after the rewrite: %s\n', answers{strcmp(study.describe().file_id, copy.describe().file_id) + 1});
study.close();
copy.close();
found = gamut.validate('converged.gamut');
fprintf('valid: %s\n', answers{(isempty(found) || ~any(startsWith({found.rule}, 'E'))) + 1});
```

///

/// tab | Julia

```julia
sweep("monday.gamut", [0.5, 0.6, 0.7])
sweep("tuesday.gamut", [0.8, 0.9])
println("appended ", GamutFile.append!("monday.gamut", "tuesday.gamut"), " runs")

good = GamutFile.open(study -> GamutFile.select(study, "status == converged"), "monday.gamut")
GamutFile.extract("monday.gamut", "converged.gamut", good)
GamutFile.write_copy("converged.gamut", "converged_copy.gamut")

GamutFile.open("converged.gamut") do study
    GamutFile.open("converged_copy.gamut") do copy
        println("kept ids: ", join(GamutFile.get_row_ids(study), " "), " at mach ",
                join((@sprintf("%g", m) for m in GamutFile.get_parameter(study, "mach")), " "))
        same = GamutFile.describe(study)["file_id"] == GamutFile.describe(copy)["file_id"]
        println("same file id after the rewrite: ", same ? "yes" : "no")
    end
end
println("valid: ", all(f -> f.severity != "error", GamutFile.validate("converged.gamut")) ? "yes" : "no")
```

///

/// tab | C++

```cpp
sweep("monday.gamut", {0.5, 0.6, 0.7});
sweep("tuesday.gamut", {0.8, 0.9});
std::printf("appended %lld runs\n", (long long)gamut::append("monday.gamut", "tuesday.gamut"));

const auto good = gamut::open("monday.gamut").select("status == converged");
gamut::extract("monday.gamut", "converged.gamut", good);
gamut::write_copy("converged.gamut", "converged_copy.gamut");

const auto study = gamut::open("converged.gamut"), copy = gamut::open("converged_copy.gamut");
std::printf("kept ids:");
for (const int64_t id : study.get_row_ids()) std::printf(" %lld", (long long)id);
std::printf(" at mach");
for (const double mach : study.get_parameter<double>("mach")) std::printf(" %g", mach);
std::printf("\n");
const bool same = study.describe()["file_id"] == copy.describe()["file_id"];
std::printf("same file id after the rewrite: %s\n", same ? "yes" : "no");
std::printf("valid: %s\n", gamut::validate("converged.gamut").ok ? "yes" : "no");
```

///

/// tab | Rust

```rust
sweep("monday.gamut", &[0.5, 0.6, 0.7])?;
sweep("tuesday.gamut", &[0.8, 0.9])?;
println!("appended {} runs", gamut::append("monday.gamut", "tuesday.gamut")?);

let good = gamut::open("monday.gamut")?.select("status == converged")?;
gamut::extract("monday.gamut", "converged.gamut", good)?;
gamut::write_copy("converged.gamut", "converged_copy.gamut")?;

let (study, copy) = (gamut::open("converged.gamut")?, gamut::open("converged_copy.gamut")?);
let ids = study.get_row_ids(..)?;
let machs: Vec<f64> = study.get_parameter("mach", ..)?;
println!("kept ids:{} at mach{}", ids.iter().map(|id| format!(" {id}")).collect::<String>(),
         machs.iter().map(|m| format!(" {m}")).collect::<String>());
let same = study.describe("")?["file_id"] == copy.describe("")?["file_id"];
println!("same file id after the rewrite: {}", if same { "yes" } else { "no" });
println!("valid: {}", if gamut::validate("converged.gamut")?.ok { "yes" } else { "no" });
```

///

Each prints:

```text
appended 2 runs
kept ids: 0 1 2 3 at mach 0.5 0.6 0.7 0.8
same file id after the rewrite: yes
valid: yes
```

### Append

Both files need the same declarations (bounds may differ) and
the same mesh. Appended runs get new ids that continue the destination's.
Category tables merge by name, so a status `failed` in one file is
`failed` in the other whatever its code. A group member found in both
files must have the same geometry in both.

A file may carry a portion marking, its author's free text about who may
see it (`portion_marking` when it is created). Appending keeps the
destination's: runs from an unmarked file take it, and runs from a file
marked otherwise are refused (E27), since they would lose their own. To
append them, state the marking the result carries:
`append(dst, src, marking=m)` in Python, `gamut.append(dst, src, 'Marking', m)`
in MATLAB, `GamutFile.append!(dst, src; marking=m)` in Julia,
`gamut::append(dst, src, m)` in C++, `gamut::append_marked(dst, src, m)`
in Rust, and `gamut append FILE SRC --marking TEXT` on the command line.
The destination then carries it, whatever the two files did; an empty
marking is none, and is never stated.

### Extract

The chosen runs keep their ids, so a run can be traced back
to the study it came from. Tables are kept whole; a changing mesh keeps
only the meshes the chosen runs use.

### Write copy

The copy has the default chunk shapes and compression, as
for a file another writer chunked finely, and keeps the original's
identity: its `file_id` and creation time.

## Notes

- To add runs as they finish, open the file to append instead
  ([run tables](01-run-tables.md#notes) gives each language's spelling):
  it takes `add_run` and `add_runs` as a new file does. A batch refused
  for its data (a missing value, a wrong shape) adds nothing and changes
  no run. The runs go to a copy beside the file, which replaces it when
  the file closes: a process killed while it appends, by a crash or a
  job's time limit, or a write that fails (a full disk), loses the runs
  of that session and leaves the file as it was, and `append` adds all of
  a source's runs or none. The copy is a clone, which costs nothing, on
  filesystems that make them (APFS, Btrfs, XFS); elsewhere it is a
  full copy, so close the file once per batch of runs rather than once
  per run. One process appends to a file at a time, and only on a
  filesystem with file locks; others can read it meanwhile, and a reader
  that opens it after it closes sees the new runs.
- Opening a file that carries a portion marking shows it, once per file
  in a process: a block naming the file, then the marking whole, the same
  in every language. Python prints it on `sys.stderr` (so it shows in a
  notebook), C, C++, Rust and the command line on stderr, Julia logs it
  with `@info`, and MATLAB issues the warning `gamut:marking`.
  `gamut.set_marking_notice` routes it: `False` turns it off and a
  function of the path and the text receives it; Julia, C++ and Rust have
  `set_marking_notice` too, MATLAB `warning('off', 'gamut:marking')`, and
  the command line `gamut --no-marking-notice` (and `gamut-vtk`'s). A program that turns it
  off takes on any duty to show the marking: Gamut cannot make anything
  display it, since any HDF5 tool reads the file.
- `validate` checks a file against the rules of the specification. Each
  finding has its rule, the path of what it concerns and a message; Python
  C++ and Rust return a report with `ok`, `errors` and `warnings`, MATLAB and
  Julia the findings, each with its severity.

Run it: `python examples/09_combining_files.py`, or `combining` from
`examples/matlab`, `examples/julia` and `examples/cpp`
([installing](../install.md) says how to run each). Next: [VTK](10-vtk.md).

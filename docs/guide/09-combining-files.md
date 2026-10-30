# 9. Combining files

Studies grow: a second batch of runs on another day, a few failed runs
repeated. Three calls move runs between files, and each checks everything
before it writes the first row, so a refused call leaves both files as they
were.

| Call | Does |
|---|---|
| `append(dst, src)` | adds `src`'s runs to `dst` in place |
| `extract(src, dst, rows)` | writes chosen runs of `src` as a new file |
| `write_copy(src, dst)` | rewrites a file with the default layout |

MATLAB spells them `gamut.append`, `gamut.extract` and `gamut.writeCopy`,
Julia `Gamut.append!`, `Gamut.extract` and `Gamut.write_copy`, and C++
`gamut::append`, `gamut::extract` and `gamut::write_copy`. Row ids are the
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
println("appended ", Gamut.append!("monday.gamut", "tuesday.gamut"), " runs")

good = Gamut.open(study -> Gamut.select(study, "status == converged"), "monday.gamut")
Gamut.extract("monday.gamut", "converged.gamut", good)
Gamut.write_copy("converged.gamut", "converged_copy.gamut")

Gamut.open("converged.gamut") do study
    Gamut.open("converged_copy.gamut") do copy
        println("kept ids: ", join(Gamut.get_row_ids(study), " "), " at mach ",
                join((@sprintf("%g", m) for m in Gamut.get_parameter(study, "mach")), " "))
        same = Gamut.describe(study)["file_id"] == Gamut.describe(copy)["file_id"]
        println("same file id after the rewrite: ", same ? "yes" : "no")
    end
end
println("valid: ", all(f -> f.severity != "error", Gamut.validate("converged.gamut")) ? "yes" : "no")
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
  it takes `add_run` and `add_runs` as a new file does, without copying
  the file. A batch refused for its data (a missing value, a wrong shape) leaves the
  file as it was. A process killed while it appends, by a crash or a job's
  time limit, or a write that fails (a full disk), can leave the whole file
  unreadable, the runs written before included:
  keep a copy of a file you cannot regenerate before appending to it, or
  write each job's runs to a file of its own and `append` them at the end.
- `validate` checks a file against the rules of the specification. Each
  finding has its rule, the path of what it concerns and a message; Python
  and C++ return a report with `ok`, `errors` and `warnings`, MATLAB and
  Julia the findings, each with its severity.

Run it: `python examples/09_combining_files.py`, or `combining` from
`examples/matlab`, `examples/julia` and `examples/cpp`
([installing](../install.md) says how to run each). Next: [VTK](10-vtk.md).

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

The example writes two days of a Mach sweep, appends the second to the
first, keeps the converged runs, and rewrites that file.

```python
sweep("monday.gamut", [0.5, 0.6, 0.7])
sweep("tuesday.gamut", [0.8, 0.9])
print("appended", gamut.append("monday.gamut", "tuesday.gamut"), "runs")

with gamut.open("monday.gamut") as study:
    good = study.select("status == converged")
gamut.extract("monday.gamut", "converged.gamut", good)
gamut.write_copy("converged.gamut", "converged_copy.gamut")

with gamut.open("converged.gamut") as study, gamut.open("converged_copy.gamut") as copy:
    print("kept ids:", study.get_row_ids(), "mach:", study.get_parameter("mach"))
    print("same file id after the rewrite:", study.describe()["file_id"] == copy.describe()["file_id"])
print("valid:", gamut.validate("converged.gamut").ok)
```

```text
appended 2 runs
kept ids: [0 1 2 3] mach: [0.5 0.6 0.7 0.8]
same file id after the rewrite: True
valid: True
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

- To add runs as they finish, open the file to append instead:
  `gamut.open(path, mode="a")` takes `add_run` and `add_runs` as `create`
  does, without copying the file. A batch refused for its data (a missing value, a wrong shape) leaves the
  file as it was. A process killed while it appends, by a crash or a job's
  time limit, or a write that fails (a full disk), can leave the whole file
  unreadable, the runs written before included:
  keep a copy of a file you cannot regenerate before appending to it, or
  write each job's runs to a file of its own and `append` them at the end.
- `validate` checks a file against the rules of the specification and
  returns a report: `ok`, then `errors` and `warnings`, each finding with
  its rule, the path of what it concerns, and a message.

Run it: `python examples/09_combining_files.py`. Next: [VTK](10-vtk.md).

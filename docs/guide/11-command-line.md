# 11. Command line

`gamut` inspects, checks, builds and extracts study files without code:
for a quick look at a file someone sent, for shell scripts, and for tools
in other languages. Data goes to files, and problems are reported all at
once, each with what it concerns.

The sessions below run in a folder holding the files of the first two
examples (`polar.gamut`, `cylinder.gamut`) and the documents in
[`examples/cli/`](../../examples/cli).

## Looking inside

```console
$ gamut info cylinder.gamut
cylinder.gamut: shared mesh, 9 runs
  mesh        576 nodes, 528 cells, fixed
  parameters  gamma [m2 s-1] 0 to 4
  fields      cp [1] at nodes
  zones       surface: field, wall
  file        ... KB
$ gamut validate polar.gamut
no errors, 3 warnings
  W2 status: 1 row is not converged (1 failed), the first row 17; tools that train on the file skip such rows unless told otherwise
  W3 cd: 1 value is missing or not finite, the first at row 17
  W3 cl: 1 value is missing or not finite, the first at row 17
```

`validate` checks the rules of the [specification](../../SPEC.md) and
names each one it finds broken, within the [limits](../security.md#the-limits)
of what it reads. Errors make a file invalid; warnings say
what a reader should know, such as runs that failed. A row in a finding
is a position in the file, counted from 0 as `select` counts, not a row
id.

## Taking data out

```console
$ gamut get polar.gamut mach alpha cl --where "status == converged" -o polar.csv
wrote polar.csv: mach 17 [1], alpha 17 [degree], cl 17 [1]
$ gamut get cylinder.gamut cp --zone surface=wall --rows 0:3 -o wall.npy
wrote wall.npy: cp 3x48 [1]
$ gamut get polar.gamut --where "mach == 0.7" -o mach07.gamut
wrote 6 runs to mach07.gamut
```

- `--where` chooses runs by condition, `--rows` by position (`0:3`, or
  `2,5,9`), and `--zone LABEL=NAME` the nodes or cells of one zone.
- An output that exists is refused; `--force` replaces a `.csv`, `.npy` or
  `.npz` one, and a `.gamut` file is never written over.
- The output's extension decides its form: `.csv` (one line per run, its
  id first; a field goes alone, a column per node), `.npy` (one array),
  `.npz` (several, with the row ids), or `.gamut`, a smaller study file with
  the chosen runs and their ids.

## Building a file

A file can be built from a JSON document that declares what it holds, and
a CSV with one line per run:

```json
{
  "writer": "wind tunnel log",
  "title": "Model B, first entry",
  "parameters": {"mach": {"units": "1", "role": "condition"},
                 "alpha": {"units": "degree", "role": "condition"}},
  "labels": {"status": {"role": "status", "categories": ["converged", "failed"]}},
  "scalars": {"cl": "1", "cd": "1"},
  "runs": "sweep_runs.csv"
}
```

```csv
mach,alpha,status,cl,cd
0.3,0,converged,0.012,0.0081
0.3,4,converged,0.452,0.0154
0.5,0,converged,0.014,0.0083
0.5,4,failed,nan,nan
```

```console
$ gamut build sweep.json -o sweep.gamut
wrote sweep.gamut: 4 runs
$ gamut append sweep.gamut second_entry.json
appended 2 runs to sweep.gamut
```

The declarations are those of `gamut.create` ([run tables](01-run-tables.md)).
An appended document needs only its `runs`; `gamut append` also takes
another study file and adds all of its runs. For fields, the document names
a mesh file (`.npz`), and each run's line names a `.npy` of its values;
`gamut build --example` prints a complete document with the layout of
both explained.

## For scripts

- `--json` makes any command print one JSON document instead, of a shape
  that stays the same across versions; `gamut get` still writes its data
  to the output file. Every failure under `--json` is one shape,
  `{"problems": [{"rule", "path", "message"}]}`, a misused command
  included.
- The exit status is 0 on success, 1 when a file or document has errors,
  and 2 for a command used wrongly.
- `gamut --version` gives the package version and the format version it
  writes.

Next: [MATLAB](12-matlab.md).

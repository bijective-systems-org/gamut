# 10. VTK

Many studies today are a folder of VTK files, one per run. `mestra-vtk`
turns such a folder into one study file, and a study file back into a
folder of `.vtu` files, so nothing is locked in. It needs the `vtk` extra:
`pip install "mestra[vtk]"`.

## From the command line

```bash
mestra-vtk import runs/ -o study.mes      # .vtu, .vtp or legacy .vtk, one per run
mestra-vtk export study.mes back/         # one .vtu per run, and the two tables
```

A VTK file knows its arrays but not what the run was, nor what units the
arrays are in. The first `import` writes two small tables beside the runs
for you to fill in, and stops:

- `parameters.csv`: one line per run, the file name and then each
  parameter or label, with a line of units under the header;
- `fields.csv`: the units of each array, and of the coordinates.

Once they are filled in, the same command writes the study. Every problem
it finds is listed at once, with the file it concerns.

## From Python

The example writes three runs as `.vtu` files with PyVista, then imports
them:

```python
first = vtk.import_folder(folder, "from_vtk.mes")         # writes two tables, then stops
print("to fill in:", ", ".join(os.path.basename(t) for t in first["templates"]))
with open(f"{folder}/parameters.csv", "w") as table:
    table.write("file,gamma\nunits,m2 s-1\n" +
                "".join(f"run_{k:03d}.vtu,{g}\n" for k, g in enumerate((0.0, 2.0, 4.0))))
with open(f"{folder}/fields.csv", "w") as table:
    table.write("name,units\ncoordinates,m\ncp,1\n")
report = vtk.import_folder(folder, "from_vtk.mes")
print(report["rows"], "runs imported, geometry", report["geometry"])
print("written back:", vtk.export_study("from_vtk.mes", "back")["files"])
```

```text
to fill in: parameters.csv, fields.csv
3 runs imported, geometry fixed
written back: ['run_000.vtu', 'run_001.vtu', 'run_002.vtu']
```

## What the import decides

- A number column of `parameters.csv` is a parameter, a text column a
  label. An optional `role` line under the units says otherwise:
  `condition`, `design`, `time`, `group`, `status`.
- A parameter with the role `time` and one `group` label make a set of
  transient runs ([time series](05-time-series.md)).
- An array of three components becomes a vector of three fields (`U_x`,
  `U_y`, `U_z`), declared as one vector.
- An integer array becomes a mesh label, such as a zone or a patch; on one
  mesh it must be the same in every run.
- Runs with the same cells share [one mesh](02-one-mesh.md), its geometry
  stored once if it never moves and once per run if it does.
- Runs with different cells, each meshed on its own, keep a mesh each: a
  [changing mesh](04-changing-meshes.md), read one run at a time.

## Worth knowing

- `--skip a,b` leaves arrays out; `--round-bits N` keeps N significant
  bits of each value, so the file compresses further (the bits kept are
  recorded in the file).
- `--json` prints the report as JSON, for scripts. The exit status is 0
  when done, 1 when refused, and 2 when the tables are waiting to be
  filled in.
- `to_pyvista(study, row)` and `from_pyvista(mesh)` in `mestra.vtk` are
  the bridge, and a worked example for a converter from another format.

Run it: `python examples/10_vtk.py`. Next: [the command line](11-command-line.md).

# 8. Reading parts

A study file can be much larger than memory. Reads name what they want:
runs by a condition, nodes or cells by position or by zone, and the units
the values should arrive in.

The example writes pressure on the cylinder of [page 2](02-one-mesh.md) at
three speeds and three circulations, then reads the wall pressure of some
of the runs, in kilopascals.

## Reading

```python
with mestra.open("parts.mes") as study:
    rows = study.select("speed >= 20 and gamma > 1 and status == converged")
    print("chosen rows:", rows)
    wall = study.categories("surface").index("wall")
    on_wall = np.flatnonzero(study.get_mesh_label("surface") == wall)
    p_wall = study.get_field("p", rows=rows, nodes=on_wall, units="kPa")
    print("wall pressure block:", p_wall.shape, "lowest", p_wall.min().round(3), "kPa")
    print("speeds in km/h:", study.get_parameter("speed", rows=rows, units="km/h").round(1))
```

```text
chosen rows: [4 5 7 8]
wall pressure block: (4, 48) lowest -5.833 kPa
speeds in km/h: [ 72.  72. 144. 144.]
```

**Runs.** `select` compares parameters, scalars and labels with `==`, `!=`,
`<`, `<=`, `>`, `>=`, joined by `and`, `or`, `not` and parentheses. A
label compares by name, with quotes when the name has spaces:
`model == "k-omega SST"`. The [reference](../reference/selecting.md) has
the whole grammar. Any list of positions works as `rows` too, so a
selection can come from NumPy just as well.

**Nodes and cells.** `nodes` and `cells` take a position, a list, or a
slice. A zone comes from a mesh label: `categories` gives its names, and
the positions where the label holds a name's code are that zone.

**Units.** Every read takes `units`, and converts from the stored units.
Conversion needs the `units` extra (`pip install "mestra[units]"`, which
brings pint); without it, a read that asks for other units is refused.
Leave `units` out to get values in the units they were stored in, which
`describe(name)["units"]` names.

## Worth knowing

- Writing converts too: a value given as `(number, "units")` in `add_run`
  is converted to the declared units before it is stored.
- `mestra.open(path, threads=4)` decompresses large field reads in four
  threads, with the same result as one.
- Opening a file reads its structure and attributes only. Nothing else is
  read until it is asked for.

Run it: `python examples/08_selecting_parts.py`. Next: [combining files](09-combining-files.md).

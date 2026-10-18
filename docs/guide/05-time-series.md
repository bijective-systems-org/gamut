# 5. Time series

A transient run saves its state many times. Each saved step is a row, with
time as a parameter, and a group label says which run each row belongs to.
The steps of one run then read like any other rows, and tools keep them
together: a viewer animates one run, and a model trained on the study is
tested on runs it has not seen rather than on steps between ones it has.

The example is two runs at two speeds, each saved at 101 steps, with a
lift coefficient that oscillates as vortex shedding behind a cylinder
would make it.

## Writing

```python
with mestra.create("transient.mes", writer="example transient",
                   labels={"run": {"role": "group"}},
                   parameters={"t": {"units": "s", "role": "time", "run_group": "run"},
                               "speed": {"units": "m s-1", "role": "condition"}},
                   scalars={"cl": "1"}) as study:
```

- The parameter `t` has the role `time`, and `run_group` names the label
  that groups its rows into runs.
- The label `run` declares no categories: its table grows as new names
  appear.

`add_runs` adds many rows at once, a column per name:

```python
study.add_runs({"run": [name] * len(steps), "t": steps,
                "speed": np.full(len(steps), speed), "cl": cl})
```

## Reading

```python
with mestra.open("transient.mes") as study:
    print(study.row_count, "rows; add-ons:", study.addons)
    fast = study.select("run == fast")
    t, cl = study.get_parameter("t", rows=fast), study.get_scalar("cl", rows=fast)
    print(f"fast run: {len(fast)} steps, peak |cl| {np.abs(cl).max():.2f} after t = {t[np.abs(cl).argmax()]:.1f} s")
```

```text
202 rows; add-ons: ['time']
fast run: 101 steps, peak |cl| 0.80 after t = 7.5 s
```

A file reports what it holds beyond its type as *add-ons*: `time` here;
`uncertainty` and `gradients` on the [next page](06-uncertainty-and-gradients.md).

## Worth knowing

- Runs may differ in length and in their save times, and their rows need
  not be contiguous. Two rows of one run at the same time are reported.
- With a mesh, every step brings its fields like any other row. A history
  sampled at the same times in every run is rows too, not a separate case.
- A single transient run needs no group label.

Run it: `python examples/05_time_series.py`. Next: [uncertainty and gradients](06-uncertainty-and-gradients.md).

"""Transient runs: every saved step is a row.

Two transient runs, each saved at many time steps. Time is a parameter with
the role `time`, and a group label says which run each step belongs to, so
tools keep a run's steps together.
"""
import numpy as np

import gamut

steps = np.linspace(0.0, 10.0, 101)
with gamut.create("transient.gamut", writer="example transient",
                   labels={"run": {"role": "group"}},
                   parameters={"t": {"units": "s", "role": "time", "run_group": "run"},
                               "speed": {"units": "m s-1", "role": "condition"}},
                   scalars={"cl": "1"}) as study:
    for name, speed in (("slow", 20.0), ("fast", 35.0)):
        frequency = 0.2 * speed / 10.0                       # shedding, Strouhal 0.2
        cl = 0.8 * np.sin(2 * np.pi * frequency * steps) * (1 - np.exp(-steps))
        study.add_runs({"run": [name] * len(steps), "t": steps,
                        "speed": np.full(len(steps), speed), "cl": cl})

with gamut.open("transient.gamut") as study:
    print(study.row_count, "rows; add-ons:", study.addons)
    fast = study.select("run == fast")
    t, cl = study.get_parameter("t", rows=fast), study.get_scalar("cl", rows=fast)
    print(f"fast run: {len(fast)} steps, peak |cl| {np.abs(cl).max():.2f} after t = {t[np.abs(cl).argmax()]:.1f} s")

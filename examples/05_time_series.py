"""Transient runs: every saved step is a row.

Two transient runs, each saved at many time steps. Time is a parameter with
the role `time`, and a group label says which run each step belongs to, so
tools keep a run's steps together. The MATLAB, Julia and C++ examples
transient are the same program and print the same lines.
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
    print(f"{study.row_count} rows, {len(study.categories('run'))} runs")
    fast = study.select("run == fast")
    t, cl = study.get_parameter("t", rows=fast), study.get_scalar("cl", rows=fast)
    peak = np.abs(cl).argmax()
    print(f"fast run: {len(fast)} steps, peak |cl| {abs(cl[peak]):.2f} at t = {t[peak]:.1f} s")

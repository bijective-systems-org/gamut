"""A sweep of a wing's angle of attack: six runs written, a seventh added, then read.

Each run records its input, whether it converged, and its lift; the six
are written at once, as columns, and a failed seventh is added later. The
lift of the runs that converged is read back, as a model fitted to the
study would read it. examples/matlab, julia and cpp hold the same program
in those languages, and all four print the same line.
"""
import numpy as np

import gamut

alpha = np.arange(0.0, 11.0, 2.0)  # six angles of attack, in degrees
cl = 0.11 * alpha                  # stands for the solver's lift coefficients

with gamut.create("sweep.gamut", writer="example sweep",
                   parameters={"alpha": {"units": "degree", "role": "condition"}},
                   labels={"status": {"role": "status",
                                      "categories": ["converged", "failed"]}},
                   scalars={"cl": "1"}) as study:
    study.add_runs({"alpha": alpha, "cl": cl,
                    "status": ["converged"] * len(alpha)})

with gamut.open("sweep.gamut", mode="a") as study:
    study.add_run({"alpha": 12, "status": "failed"})

with gamut.open("sweep.gamut") as study:
    lift = study.get_scalar("cl", rows=study.select("status == converged"))
print("lift of the runs that converged:", " ".join(f"{v:.2f}" for v in lift))

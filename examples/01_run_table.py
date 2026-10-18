"""A study with no mesh: a table of runs, each with its inputs and results.

A sweep of a wing over Mach number and angle of attack. Each run records
its inputs (parameters), whether the solver converged (a label), and its
force coefficients (scalars), every one with its units.
"""
import numpy as np

import mestra

with mestra.create("polar.mes", writer="example sweep",
                   parameters={"mach": {"units": "1", "role": "condition"},
                               "alpha": {"units": "degree", "role": "condition"}},
                   labels={"status": {"role": "status", "categories": ["converged", "failed"]}},
                   scalars={"cl": "1", "cd": "1"},
                   constants={"reference_area": (12.5, "m2")},
                   title="Wing A polar") as study:
    for mach in (0.6, 0.7, 0.8):
        for alpha in range(-2, 9, 2):
            cl = 0.11 * alpha / np.sqrt(1 - mach**2)        # stand-in for a solver
            cd = 0.008 + 0.04 * cl**2
            failed = mach == 0.8 and alpha == 8
            study.add_run({"mach": mach, "alpha": float(alpha),
                           "status": "failed" if failed else "converged",
                           "cl": np.nan if failed else cl, "cd": np.nan if failed else cd})

with mestra.open("polar.mes") as study:
    print(study.row_count, "runs;", study.describe()["title"])
    print("lift at Mach 0.7:", study.get_scalar("cl", rows=study.select("mach == 0.7")).round(3))
    print("runs that failed:", study.select("status == failed"))
    print("reference area:", study.get_constant("reference_area"), study.describe("reference_area")["units"])

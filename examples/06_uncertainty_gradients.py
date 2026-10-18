"""Uncertainty and gradients beside the values they describe.

Each run stores a lift coefficient with its standard deviation and two
quantiles (from an ensemble), and its derivative with respect to angle of
attack (from an adjoint). Each statistic names the result it describes, so
a reader finds them without naming conventions.
"""
import numpy as np

import mestra

alpha = np.linspace(0.0, 8.0, 9)
cl = 0.11 * alpha
with mestra.create("uncertain.mes", writer="example ensemble",
                   parameters={"alpha": {"units": "degree"}},
                   scalars={"cl": "1",
                            "cl_std": {"units": "1", "of": "cl", "statistic": "std"},
                            "cl_p05": {"units": "1", "of": "cl", "statistic": "quantile", "q": 0.05},
                            "cl_p95": {"units": "1", "of": "cl", "statistic": "quantile", "q": 0.95},
                            "dcl_dalpha": {"units": "degree-1", "of": "cl",
                                           "with_respect_to": "alpha"}}) as study:
    spread = 0.01 + 0.002 * alpha
    study.add_runs({"alpha": alpha, "cl": cl, "cl_std": spread,
                    "cl_p05": cl - 1.645 * spread, "cl_p95": cl + 1.645 * spread,
                    "dcl_dalpha": np.full(9, 0.11)})

with mestra.open("uncertain.mes") as study:
    related = study.related("cl")
    print("what describes cl:", related)
    low = study.get_scalar(related["quantiles"][0.05])
    high = study.get_scalar(related["quantiles"][0.95])
    print("90 % band at 8 degrees:", round(float(low[-1]), 3), "to", round(float(high[-1]), 3))

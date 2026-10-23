"""A sweep of a wing's angle of attack: six runs written, a seventh added, then read.

Each run records its input, whether it converged, and its lift; the lift of
the runs that converged is read back, as a model fitted to the study would
read it. examples/matlab, julia and cpp hold the same program in those
languages, and all four print the same line.
"""
import gamut


def solve(alpha):
    """Stands for the solver: the lift coefficient at one angle of attack."""
    return 0.11 * alpha


with gamut.create("sweep.gamut", writer="example sweep",
                   parameters={"alpha": {"units": "degree", "role": "condition"}},
                   labels={"status": {"role": "status", "categories": ["converged", "failed"]}},
                   scalars={"cl": "1"}) as study:
    for alpha in range(0, 11, 2):
        study.add_run({"alpha": alpha, "status": "converged", "cl": solve(alpha)})

with gamut.open("sweep.gamut", mode="a") as study:
    study.add_run({"alpha": 12, "status": "failed"})

with gamut.open("sweep.gamut") as study:
    cl = study.get_scalar("cl", rows=study.select("status == converged"))
print("lift of the runs that converged:", " ".join(f"{v:.2f}" for v in cl))

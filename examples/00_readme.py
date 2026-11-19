"""Write three runs to first.gamut and read back the lift coefficients."""
import gamut

# Values at the same position belong to the same run.
alpha = [0.0, 2.0, 4.0]
cl = [0.0, 0.22, 0.44]

with gamut.create(
    "first.gamut",
    writer="example sweep",
    parameters={"alpha": {"units": "degree", "role": "condition"}},
    scalars={"cl": "1"},
) as study:
    study.add_runs({"alpha": alpha, "cl": cl})

with gamut.open("first.gamut") as study:
    lift = study.get_scalar("cl")

print("cl:", " ".join(f"{value:.2f}" for value in lift))

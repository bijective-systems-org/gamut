"""Fit, save and evaluate a model of lift versus angle of attack.

A model file holds no runs and no code: its parameters carry the range the
model was fitted on, each result names the model and output that computes
it, and the model's own numbers are plain data. Evaluating it on new inputs
gives an ordinary data file.

The model here is a quadratic of a type of our own, `Polynomial`.
examples/matlab/models.m is the same program in MATLAB, with a MATLAB class
of the same type, and prints the same lines; examples/matlab/evaluate_model.m
evaluates the file this program writes. The built-in
`Nearest` model answers with the closest run; examples/julia/nearest.jl
and examples/cpp/nearest.cpp evaluate it too. Last, the model is asked
about an angle outside the range it was fitted on, and the answer says so.
"""
import numpy as np

import gamut

# Training sweep with six converged runs and one failed run.
with gamut.create("training_sweep.gamut", writer="example sweep",
                   parameters={"alpha": {"units": "degree", "role": "condition"}},
                   labels={"status": {"role": "status", "categories": ["converged", "failed"]}},
                   scalars={"cl": "1"}) as study:
    for alpha in range(0, 11, 2):
        study.add_run({"alpha": alpha, "status": "converged", "cl": 0.11 * alpha})
    study.add_run({"alpha": 12, "status": "failed"})


@gamut.register_model_type
class Polynomial:
    """A polynomial in one input, highest power first, as numpy.polyfit gives it."""
    type = "example.polynomial"

    def __init__(self, coefficients):
        self.coefficients = np.asarray(coefficients, dtype=float)

    @classmethod
    def load(cls, numbers):
        return cls(numbers["coefficients"])

    def save(self):
        return {"coefficients": self.coefficients}

    def call(self, inputs, wanted):
        (x,) = inputs.values()
        return {output: {"values": np.polyval(self.coefficients, x)} for output, *_ in wanted}


with gamut.open("training_sweep.gamut") as study:
    rows = study.select("status == converged")
    alpha, cl = study.get_parameter("alpha", rows=rows), study.get_scalar("cl", rows=rows)
    sweep_id = study.describe()["file_id"]

with gamut.create_model("lift_model.gamut", writer="example fit", trained_on=[sweep_id],
                         parameters={"alpha": {"units": "degree", "lower": 0.0, "upper": 10.0}},
                         scalars={"cl": {"units": "1", "model": "fit", "output": "cl"}}) as model:
    model.add_model("fit", Polynomial(np.polyfit(alpha, cl, 2)), inputs=["alpha"])

with gamut.evaluate("lift_model.gamut", {"alpha": [2.2, 7.9]}, path="lift_answer.gamut") as answer:
    lift = answer.get_scalar("cl")
print("the model's lift at 2.2 and 7.9 degrees:", " ".join(f"{v:.2f}" for v in lift))
print("the answer is a valid study file:", "yes" if gamut.validate("lift_answer.gamut").ok else "no")

# The built-in model: the closest run, evaluated by the core in every language.
with gamut.create_model("lift_nearest.gamut", writer="example fit", trained_on=[sweep_id],
                         parameters={"alpha": {"units": "degree", "lower": 0.0, "upper": 10.0}},
                         scalars={"cl": {"units": "1", "model": "fit", "output": "cl"}}) as model:
    model.add_model("fit", gamut.Nearest(["alpha"], [0.0], [10.0], alpha[:, None], {"cl": cl}),
                    inputs=["alpha"])

with gamut.evaluate("lift_nearest.gamut", {"alpha": [2.2, 7.9]}) as answer:
    lift = answer.get_scalar("cl")
print("the nearest run's lift at 2.2 and 7.9 degrees:", " ".join(f"{v:.2f}" for v in lift))

# Inputs outside the range the model was fitted on are evaluated, with a
# warning (W4), and the answer says for each row how far outside it lies.
with gamut.evaluate("lift_model.gamut", {"alpha": [5.0, 12.0]}) as answer:
    lift, outside = answer.get_scalar("cl"), answer.outside("alpha")
print("the model's lift at 5 and 12 degrees:", " ".join(f"{v:.2f}" for v in lift))
print("degrees outside the fitted range:", " ".join(f"{v:g}" for v in outside))

# An input of many values: a wall temperature at four stations is one array.
walls = np.array([[300.0, 340.0, 380.0, 420.0], [500.0, 540.0, 580.0, 620.0]])
with gamut.create_model("heating_nearest.gamut", writer="example fit",
                         arrays={"wall_t": {"units": "K", "length": 4, "role": "condition",
                                            "lower": 300.0, "upper": 620.0}},
                         scalars={"q": {"units": "kW m-2", "model": "fit", "output": "q"}}) as model:
    model.add_model("fit", gamut.Nearest(["wall_t"], [300.0], [620.0], walls, {"q": [41.0, 35.0]},
                                         widths=[4]), inputs=["wall_t"])

with gamut.evaluate("heating_nearest.gamut", {"wall_t": [[320.0, 350.0, 390.0, 430.0],
                                                          [480.0, 530.0, 600.0, 640.0]]}) as answer:
    q, outside = answer.get_scalar("q"), answer.outside("wall_t")
print("the nearest run's heat flux for two walls:", " ".join(f"{v:g}" for v in q), "kW m-2")
print("kelvin outside the fitted range, second wall:", " ".join(f"{v:g}" for v in outside[1]))

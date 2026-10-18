"""A model file: what a fitted model needs, and how it answers.

A model file holds no runs: its parameters carry the bounds the model was
fitted on, and each result names the model and output that computes it.
Evaluating it on new inputs gives an ordinary data file. The built-in
`Nearest` model answers with the closest stored point; any other model is a
small class registered by the software that fits it (here, a linear fit).
"""
import numpy as np

import gamut

# Training points: lift against angle of attack.
alpha = np.linspace(0.0, 10.0, 11)
cl = 0.11 * alpha - 0.002 * alpha**2

with gamut.create_model("lift_nearest.gamut", writer="example fit",
                         parameters={"alpha": {"units": "degree", "lower": 0.0, "upper": 10.0}},
                         scalars={"cl": {"units": "1", "model": "fit", "output": "cl"}}) as model:
    model.add_model("fit", gamut.Nearest(["alpha"], [0.0], [10.0], alpha[:, None], {"cl": cl}),
                    inputs=["alpha"])

with gamut.evaluate("lift_nearest.gamut", {"alpha": [2.2, 7.9]}) as answer:
    print("nearest:", answer.get_scalar("cl").round(4))


@gamut.register_model_type
class Linear:
    """cl = a + b alpha, with a standard deviation: the plug-in interface is
    a type name and three methods."""
    type = "example_linear"

    def __init__(self, a, b, std):
        self.a, self.b, self.std = a, b, std

    @classmethod
    def load(cls, numbers):
        return cls(numbers["a"], numbers["b"], numbers["std"])

    def save(self):
        return {"a": self.a, "b": self.b, "std": self.std}

    def call(self, inputs, wanted):
        x = np.asarray(inputs["alpha"])
        out = {}
        for output, kind, *_ in wanted:
            value = self.a + self.b * x if kind == "values" else np.full_like(x, self.std)
            out.setdefault(output, {})["values" if kind == "values" else "std"] = value
        return out


b, a = np.polyfit(alpha, cl, 1)
spread = float(np.std(cl - (a + b * alpha)))
with gamut.create_model("lift_linear.gamut", writer="example fit",
                         parameters={"alpha": {"units": "degree", "lower": 0.0, "upper": 10.0}},
                         scalars={"cl": {"units": "1", "model": "line", "output": "cl"},
                                  "cl_std": {"units": "1", "model": "line", "output": "cl",
                                             "of": "cl", "statistic": "std"}}) as model:
    model.add_model("line", Linear(a, b, spread), inputs=["alpha"])

with gamut.evaluate("lift_linear.gamut", {"alpha": [2.2, 7.9]}) as answer:
    print("linear:", answer.get_scalar("cl").round(4), "+/-", answer.get_scalar("cl_std").round(4))

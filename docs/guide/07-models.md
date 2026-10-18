# 7. Models

A model fitted to a study (a surrogate, a reduced-order model, a response
surface) is a file of the same shape as the data with no runs in it. Its
parameters carry the bounds the model was fitted on; each of its results
names the model that computes it. Evaluating it on new inputs gives an
ordinary data file, read with the same calls as any other.

The file never holds code. A model's own numbers are stored as plain data,
and the software that owns the model type registers it with the library to
evaluate it.

## The built-in model

`Nearest` answers with the closest stored point. It runs everywhere, in
every language with the same answers, so model files can be tested without
other software, and it is a fair baseline: the closest run you have.

```python
with gamut.create_model("lift_nearest.gamut", writer="example fit",
                         parameters={"alpha": {"units": "degree", "lower": 0.0, "upper": 10.0}},
                         scalars={"cl": {"units": "1", "model": "fit", "output": "cl"}}) as model:
    model.add_model("fit", gamut.Nearest(["alpha"], [0.0], [10.0], alpha[:, None], {"cl": cl}),
                    inputs=["alpha"])

with gamut.evaluate("lift_nearest.gamut", {"alpha": [2.2, 7.9]}) as answer:
    print("nearest:", answer.get_scalar("cl").round(4))
```

```text
nearest: [0.212 0.752]
```

- A model file's parameters need `lower` and `upper`: the domain. An input
  outside it is evaluated, with a warning; refusing it is the caller's
  choice.
- The result `cl` says it is computed by the model `fit`, output `cl`.
- `evaluate` returns the answer as a data file, open to read. Without a
  `path` it is a temporary file, removed when closed; with one, it stays.

## A model of your own

Any other model is a class with a `type` name and three methods: `load`
builds it from stored numbers, `save` turns it back into numbers, and
`call` answers. This one is a straight line with a constant spread.

```python
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
```

`call` receives the inputs it declared, an array per name with a value per
row, and the list of what is wanted, each an output's name and one of:

| Wanted | Returned in |
|---|---|
| `(output, "values")` | `out[output]["values"]` |
| `(output, "std")` | `out[output]["std"]` |
| `(output, "quantile", q)` | `out[output]["quantiles"][q]` |
| `(output, "derivative", name)` | `out[output]["derivatives"][name]` |

A scalar's values are one per row; a field's are rows × nodes (or cells).
The model file declares the spread as a result like any other, so the
answer carries it:

```python
with gamut.create_model("lift_linear.gamut", writer="example fit",
                         parameters={"alpha": {"units": "degree", "lower": 0.0, "upper": 10.0}},
                         scalars={"cl": {"units": "1", "model": "line", "output": "cl"},
                                  "cl_std": {"units": "1", "model": "line", "output": "cl",
                                             "of": "cl", "statistic": "std"}}) as model:
    model.add_model("line", Linear(a, b, spread), inputs=["alpha"])

with gamut.evaluate("lift_linear.gamut", {"alpha": [2.2, 7.9]}) as answer:
    print("linear:", answer.get_scalar("cl").round(4), "+/-", answer.get_scalar("cl_std").round(4))
```

```text
linear: [0.228 0.741] +/- [0.0177 0.0177]
```

## Worth knowing

- `save` may return nested dictionaries of numbers, text, booleans and
  NumPy arrays. Anything else is refused when the file is written, not
  when it is read.
- A file whose model type is not registered still opens, reads and
  copies; only evaluating it needs the owning software, and the refusal
  says which type is missing.
- A model may read the mesh's coordinates as an input, to predict on new
  geometries, or compute them, as a model of the geometry itself.
- `create_model(..., trained_on=[...])` records the `file_id` of each
  study the model was fitted on, and an evaluated file records the model
  file it came from.

Run it: `python examples/07_models.py`. Next: [reading parts](08-reading-parts.md).

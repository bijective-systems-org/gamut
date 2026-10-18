# 6. Uncertainty and gradients

A result often comes with more than its value: a spread from an ensemble or
from an unsteady run, an interval, a derivative from an adjoint solver.
Each of these is a result of its own that names the result it describes,
so a reader finds it without relying on naming conventions.

The example stores, for each angle of attack, a lift coefficient with its
standard deviation, its 5 % and 95 % quantiles, and its derivative with
respect to angle of attack.

## Writing

```python
scalars={"cl": "1",
         "cl_std": {"units": "1", "of": "cl", "statistic": "std"},
         "cl_p05": {"units": "1", "of": "cl", "statistic": "quantile", "q": 0.05},
         "cl_p95": {"units": "1", "of": "cl", "statistic": "quantile", "q": 0.95},
         "dcl_dalpha": {"units": "degree-1", "of": "cl",
                        "with_respect_to": "alpha"}}) as study:
```

- `of` names the result being described.
- `statistic` is `std` (a standard deviation, never negative) or
  `quantile` with `q` between 0 and 1. A symmetric interval is two
  quantiles. Its units are those of the result it describes.
- `with_respect_to` makes a derivative: with respect to a parameter, as
  here, or with respect to node position (`"coordinates"` with an `axis`),
  which is an adjoint shape sensitivity stored as a node field per axis.
- Anything else, such as an RMS, a time average or a maximum, is an
  ordinary result with a descriptive name.

## Reading

```python
with gamut.open("uncertain.gamut") as study:
    related = study.related("cl")
    print("what describes cl:", related)
    low = study.get_scalar(related["quantiles"][0.05])
    high = study.get_scalar(related["quantiles"][0.95])
    print("90 % band at 8 degrees:", round(float(low[-1]), 3), "to", round(float(high[-1]), 3))
```

```text
what describes cl: {'std': 'cl_std', 'quantiles': {0.05: 'cl_p05', 0.95: 'cl_p95'}, 'derivatives': {'alpha': 'dcl_dalpha'}, 'vector': []}
90 % band at 8 degrees: 0.837 to 0.923
```

`related` finds everything that describes a result, so a plotting script
draws error bars, and a training script collects gradients, without knowing
the names the producer chose.

## Notes

- Fields take the same declarations: a field can have a `std` field, and a
  scalar can have a derivative field with respect to node position.
- A [model file](07-models.md) serves the same relations: a model that
  predicts a spread declares a `std` result exactly as data does.
- A gradient over many parameters is one derivative per parameter.

Run it: `python examples/06_uncertainty_gradients.py`. Next: [models](07-models.md).

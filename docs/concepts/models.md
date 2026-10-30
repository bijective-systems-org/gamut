# Models

A model file is a Gamut file with no runs. It holds one or more models
fitted to a study, and declares what they take and what they give: the
inputs as parameters, whose bounds are the range the model was fitted
on, and labels; the results as scalars and fields, each naming the model
and the output that computes it; the mesh its fields live on; and the
study's constants.

```console
$ gamut info lift_model.gamut
lift_model.gamut: model file
  parameters  alpha [degree] 0 to 10
  results     cl [1]
  model       fit: example.polynomial reading alpha
  trained on  ...
  file        ... KB
```

That is the quadratic fitted in [the models example](../guide/07-models.md),
recording the study it was trained on by that file's id.

## A model is numbers, not code

A model has a type, naming the software that runs it; its inputs; and
its own numbers, stored as plain arrays and values. The format
standardizes the interface, never the internals: only the software that
owns a type reads its numbers, and a file never holds executable code.
Opening a model file from someone else runs nothing.

A type is registered with the library as three operations: **load**, from
the stored numbers to a working model; **call**, from a table of inputs
to the outputs asked for, with their standard deviations, quantiles and
derivatives when asked; and **save**, back to numbers. Python and MATLAB
register types as classes.

## Evaluating

Evaluating a model file on a table of inputs gives a data file with a row
per input: the inputs as parameters and labels, the constants, the mesh,
and every result filled by its model. It is an ordinary study, read with
the same calls as any other, and it records the model file it came from.

An input outside the range a model was fitted on is evaluated, with a
warning (W4); refusing it is the caller's choice. The answer keeps the
model's bounds on its parameters, so `outside` can say which rows lie
outside them and by how much.

## The built-in model

The type `nearest` returns, for each input row, the outputs of the
closest stored run. It is a baseline ("the closest run we have") and the
model every language can evaluate with no other software: its distance
is defined to the order of each addition, so every implementation gives
the same answer.

Running a model of another type needs the software that owns it, and
whatever licence that software requires; licensing is not part of the
format.

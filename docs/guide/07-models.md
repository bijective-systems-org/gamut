# 7. Models

A model fitted to a study, such as a response surface, a reduced-order
model or a Gaussian process, is saved as a file of the same format with no
runs in it. The file carries what the model needs to be used correctly:
the units of its inputs and results and the range of each input it was
fitted on, and, when its writer gives `trained_on`, the `file_id` of the
study it came from.

The file holds no code. The model's numbers are stored as plain data, and
the software that defines the model's type reads them, so opening a model
file runs nothing from it ([files from outside](../security.md)). A model
fitted in Python is evaluated in MATLAB with a MATLAB class of the same
type, and no Python; the built-in nearest-run model is evaluated in every
language.

Evaluating a model on new inputs gives an ordinary data file: the inputs
as parameters, the answers as results with their units, read with the same
calls as any other file and checked by `gamut validate`.

## The pattern

The model here is a quadratic fitted to the runs of the
[README's sweep](https://github.com/bijective-systems-org/gamut/blob/main/README.md#example) that converged. `Polynomial` is
its type, a class of a few lines [defined below](#a-model-type-of-your-own).

/// tab | Python

```python
with gamut.open("sweep.gamut") as study:
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
```

///

/// tab | MATLAB

```matlab
gamut.registerModelType('Polynomial');

study = gamut.open('sweep.gamut');
rows = study.select('status == converged');
alpha = study.getParameter('alpha', 'rows', rows);
cl = study.getScalar('cl', 'rows', rows);
sweepId = study.describe().file_id;
study.close();

model = gamut.createModel('lift_model.gamut', 'writer', 'example fit', 'trainedOn', {sweepId}, ...
    'parameters', struct('alpha', struct('units', 'degree', 'lower', 0, 'upper', 10)), ...
    'scalars', struct('cl', struct('units', '1', 'model', 'fit', 'output', 'cl')));
model.addModel('fit', Polynomial(polyfit(alpha, cl, 2)), {'alpha'});
model.close();

answer = gamut.evaluate('lift_model.gamut', struct('alpha', [2.2; 7.9]), 'path', 'lift_answer.gamut');
lift = answer.getScalar('cl');
answer.close();
fprintf('the model''s lift at 2.2 and 7.9 degrees: %s\n', strjoin(compose('%.2f', lift), ' '));
found = gamut.validate('lift_answer.gamut');
valid = isempty(found) || ~any(startsWith({found.rule}, 'E'));
answers = {'no', 'yes'};
fprintf('the answer is a valid study file: %s\n', answers{valid + 1});
```

///

Each prints:

```text
the model's lift at 2.2 and 7.9 degrees: 0.24 0.87
the answer is a valid study file: yes
```

- `create_model` (`createModel` in MATLAB) declares the file as `create`
  does. Its parameters need
  `lower` and `upper`: the domain. An input outside it is evaluated, with
  a warning (W4), and the answer marks it
  ([below](#inputs-outside-the-fitted-range)); refusing it is the caller's
  choice.
- Each result names the model that computes it, `fit`, and that model's
  output, `cl`. `trained_on` records the `file_id` of each study the model
  was fitted on.
- `add_model` (`addModel`) stores the numbers the model's `save` returns,
  and the inputs it reads.
- `evaluate` takes the inputs, a value per row, and returns the answer, a
  data file open to read. Without `path` it is a temporary file, removed
  when closed; with one, it stays. It records the model file it came from
  in `evaluated_from`, and carries the model file's `portion_marking` when
  its author set one (free text with `create_model`; `extract` and
  `write_copy` keep it).

Whoever receives the file sees what the model takes and gives, with none
of the model's software installed:

```console
$ gamut info lift_model.gamut
lift_model.gamut: model file
  parameters  alpha [degree] 0 to 10
  results     cl [1]
  model       fit: example.polynomial reading alpha
  trained on  ...
  file        ... KB
```

## Inputs outside the fitted range

The quadratic was fitted on angles from 0 to 10 degrees. Asked about 5
and 12 degrees, `evaluate` answers both and warns that 12 lies outside
that range (W4). A warning can be filtered and lost, so the answer keeps
the model's bounds on its parameters, and `outside` reads from them, row
by row, which inputs lie outside and how far:

/// tab | Python

```python
with gamut.evaluate("lift_model.gamut", {"alpha": [5.0, 12.0]}) as answer:
    lift, outside = answer.get_scalar("cl"), answer.outside("alpha")
print("the model's lift at 5 and 12 degrees:", " ".join(f"{v:.2f}" for v in lift))
print("degrees outside the fitted range:", " ".join(f"{v:g}" for v in outside))
```

///

/// tab | MATLAB

```matlab
answer = gamut.evaluate('lift_model.gamut', struct('alpha', [5; 12]));
lift = answer.getScalar('cl');
outside = answer.outside('alpha');
answer.close();
fprintf('the model''s lift at 5 and 12 degrees: %s\n', strjoin(compose('%.2f', lift), ' '));
fprintf('degrees outside the fitted range: %s\n', strjoin(compose('%g', outside), ' '));
```

///

Each prints:

```text
the model's lift at 5 and 12 degrees: 0.55 1.32
degrees outside the fitted range: 0 2
```

`outside(name)` gives a number per row, in the parameter's units: 0
inside the bounds or on one, the distance below the lower bound as a
negative number, above the upper as a positive one. For a model of
several inputs, ask it of each of `answer.names("parameters")`. It reads
any data file whose parameters have bounds, which `gamut validate` checks
the same way (W4), and refuses a parameter with none rather than call it
inside.

## A model type of your own

A model type is a class with a `type` name and three methods: `load`
builds the model from its stored numbers, `save` turns it back into
numbers, and `call` answers. Here is one type, `example.polynomial`, in
Python and in MATLAB; both store the same numbers, the coefficients.

/// tab | Python

```python
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
```

///

/// tab | MATLAB

```matlab
classdef Polynomial
    %POLYNOMIAL A polynomial in one input, highest power first, as polyfit
    %   gives it: the MATLAB class of the model type example.polynomial,
    %   whose Python class is in examples/07_models.py.

    properties (Constant)
        Type = 'example.polynomial'
    end

    properties
        Coefficients
    end

    methods
        function m = Polynomial(coefficients)
            m.Coefficients = coefficients;
        end

        function numbers = save(m)
            numbers = struct('coefficients', m.Coefficients);
        end

        function out = call(m, inputs, wanted)
            names = fieldnames(inputs);
            x = inputs.(names{1});
            out = struct();
            for k = 1:numel(wanted)
                out.(wanted{k}{1}).values = polyval(m.Coefficients, x);
            end
        end
    end

    methods (Static)
        function m = load(numbers)
            m = Polynomial(numbers.coefficients);
        end
    end
end
```

///

Python registers the class with `@gamut.register_model_type`, and MATLAB
by name, `gamut.registerModelType('Polynomial')`, before the first
`evaluate`. A file written in one language is evaluated in the other
with no trace of the first: [`evaluate_model.m`](https://github.com/bijective-systems-org/gamut/blob/main/examples/matlab/evaluate_model.m)
evaluates the file the Python program writes, and prints the same line.

`call` receives each input the model reads, an array with a value per row,
and the list of what is wanted. Each item names an output and what is
wanted of it: its values, its spread, a quantile or a derivative. A model
file asks for a spread or a derivative by declaring it as a result, as a
data file does ([uncertainty](06-uncertainty-and-gradients.md)).

| Wanted | Python returns | MATLAB returns |
|---|---|---|
| `(output, "values")` | `out[output]["values"]` | `out.(output).values` |
| `(output, "std")` | `out[output]["std"]` | `out.(output).std` |
| `(output, "quantile", q)` | `out[output]["quantiles"][q]` | `out.(output).quantiles(q)`, a `containers.Map` keyed by q |
| `(output, "derivative", name)` | `out[output]["derivatives"][name]` | `out.(output).derivatives.(name)` |

In MATLAB each item is a cell array, `{output, 'values'}`. A scalar's
values are one per row; a field's are rows × nodes (or cells).

The type's name is what the file records and what a reader looks up, so
name it after your project: `mylab.polynomial`.

## The built-in model

`Nearest` answers with the outputs of the closest stored point. The core
evaluates it, so it gives the same answers in every language with no
other software: a way to test a model file anywhere, and a fair baseline,
the closest run you have.

/// tab | Python

```python
with gamut.create_model("lift_nearest.gamut", writer="example fit", trained_on=[sweep_id],
                         parameters={"alpha": {"units": "degree", "lower": 0.0, "upper": 10.0}},
                         scalars={"cl": {"units": "1", "model": "fit", "output": "cl"}}) as model:
    model.add_model("fit", gamut.Nearest(["alpha"], [0.0], [10.0], alpha[:, None], {"cl": cl}),
                    inputs=["alpha"])

with gamut.evaluate("lift_nearest.gamut", {"alpha": [2.2, 7.9]}) as answer:
    lift = answer.get_scalar("cl")
print("the nearest run's lift at 2.2 and 7.9 degrees:", " ".join(f"{v:.2f}" for v in lift))
```

///

/// tab | MATLAB

```matlab
model = gamut.createModel('lift_nearest.gamut', 'writer', 'example fit', 'trainedOn', {sweepId}, ...
    'parameters', struct('alpha', struct('units', 'degree', 'lower', 0, 'upper', 10)), ...
    'scalars', struct('cl', struct('units', '1', 'model', 'fit', 'output', 'cl')));
model.addModel('fit', gamut.Nearest({'alpha'}, 0, 10, alpha, struct('cl', cl)), {'alpha'});
model.close();

answer = gamut.evaluate('lift_nearest.gamut', struct('alpha', [2.2; 7.9]));
lift = answer.getScalar('cl');
answer.close();
fprintf('the nearest run''s lift at 2.2 and 7.9 degrees: %s\n', strjoin(compose('%.2f', lift), ' '));
```

///

/// tab | Julia

```julia
answer = Gamut.evaluate("lift_nearest.gamut", Dict("alpha" => [2.2, 7.9]))
lift = Gamut.get_scalar(answer, "cl")
close(answer)
println("the nearest run's lift at 2.2 and 7.9 degrees: ", join([@sprintf("%.2f", v) for v in lift], " "))
```

///

/// tab | C++

```cpp
const gamut::Study model = gamut::open("lift_nearest.gamut");
gamut_error err;
gamut_tree* tree = nullptr;
if (gamut_model_numbers(model.handle(), "fit", &tree, &err) != 0) throw gamut::Error(err);
const std::unique_ptr<gamut_tree, void (*)(gamut_tree*)> numbers(tree, gamut_tree_free);

const char* inputs[] = {"alpha"};
const double alpha[] = {2.2, 7.9};
const double* columns[] = {alpha};
const int64_t lengths[] = {2};
double lift[2];
if (gamut_nearest_call(numbers.get(), inputs, columns, lengths, 1, 2, "cl", lift, 2, &err) != 0)
  throw gamut::Error(err);
std::printf("the nearest run's lift at 2.2 and 7.9 degrees: %.2f %.2f\n", lift[0], lift[1]);
```

///

Each prints:

```text
the nearest run's lift at 2.2 and 7.9 degrees: 0.22 0.88
```

Julia and C++ evaluate the file the Python program writes. Julia
evaluates the built-in type only, and gives any model's numbers with
`Gamut.model_numbers`. C and C++ read a model's numbers and run the
built-in model through `gamut.h`
([C++ and C](../reference/c-and-cpp.md#a-model-file)); the C++ header
does not write model files.

## Notes

- `save` may return nested dictionaries of numbers, text, booleans and
  NumPy arrays of booleans, int32, int64 or float64 (in MATLAB, a struct
  of the same). Anything else is refused when the file is written, not
  when it is read.
- A file whose model type is not registered still opens, reads and
  copies; only evaluating it needs the type's software, and the refusal
  names the type.
- `study.model_numbers("fit")` gives a model's numbers back as its `save`
  returned them, registered or not, for software that rebuilds the model
  itself.
- A model may read the mesh's coordinates as an input, to predict on new
  geometries, or compute them, as a model of the geometry itself.

Run it: `python examples/07_models.py`, or `models` from `examples/matlab`;
then, in the folder where the Python program ran, `nearest` from
`examples/julia` and `examples/cpp` ([installing](../install.md) says how
to run each). Next: [reading parts](08-reading-parts.md).

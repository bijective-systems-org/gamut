"""Model files and the plug-in interface (spec section 7, interface
section 5): model numbers as plain dictionaries, the built-in nearest
neighbour, model types registered by their owning software, and evaluation
driven from Python with the core writing the result."""

from __future__ import annotations

import ctypes
import math
import os
import tempfile
import warnings
from typing import Any, Mapping, Sequence

import numpy as np

from . import _lib
from ._lib import GamutError, b, call
from ._study import Study, _axes, _declared, _label_spec, _precision, _spec, open as _open

# --- dictionaries <-> core trees --------------------------------------------


def _to_tree(numbers: Mapping[str, Any]) -> ctypes.c_void_p:
    handle = ctypes.c_void_p()
    call("gamut_tree_new", ctypes.byref(handle))
    try:
        _fill(handle, "", numbers)
    except BaseException:
        _lib._lib.gamut_tree_free(handle)
        raise
    return handle


def _fill(h: ctypes.c_void_p, prefix: str, d: Mapping[str, Any]) -> None:
    for key, value in d.items():
        if not isinstance(key, str):
            raise GamutError("E18", f"model-data keys are strings, not {key!r}")
        path = f"{prefix}/{key}" if prefix else key
        if value is None:
            call("gamut_tree_set_null", h, b(path))
        elif isinstance(value, (bool, np.bool_)):
            call("gamut_tree_set_bool", h, b(path), 1 if value else 0)
        elif isinstance(value, (int, np.integer)):
            call("gamut_tree_set_int", h, b(path), _lib.int64_value(value, path))
        elif isinstance(value, (float, np.floating)):
            call("gamut_tree_set_float", h, b(path), float(value))
        elif isinstance(value, str):
            call("gamut_tree_set_string", h, b(path), b(value))
        elif isinstance(value, Mapping):
            call("gamut_tree_set_dict", h, b(path))
            _fill(h, path, value)
        elif isinstance(value, (list, tuple)) and value and all(isinstance(x, str) for x in value):
            call("gamut_tree_set_strings", h, b(path), _lib.string_array(list(value)), len(value))
        else:
            try:
                arr = np.asarray(value)
            except ValueError as e:   # a ragged list, say
                raise GamutError("E18", f"{path}: not an array of model data ({e})") from None
            if arr.dtype.kind in "US":
                # A list of strings was stored above: text here is mixed with
                # other values, or has more than one axis (spec section 12).
                if isinstance(value, (list, tuple)) or arr.ndim != 1:
                    raise GamutError("E18", f"{path}: text is stored as one list of strings, "
                                             "with no other values in it")
                items = [str(x) for x in arr.ravel()]
                call("gamut_tree_set_strings", h, b(path), _lib.string_array(items), len(items))
                continue
            if arr.dtype == object:
                raise GamutError("E18", f"{path}: {type(value).__name__} is not model data; save "
                                         "returns numbers, text, booleans, arrays and dictionaries")
            if arr.ndim == 0:
                raise GamutError("E18", f"{path}: a zero-dimensional array is stored as the "
                                         "number it holds")
            if arr.dtype == np.bool_:
                arr, code = arr.astype(np.int8), _lib.GAMUT_INT8
            elif arr.dtype == np.int32:
                code = _lib.GAMUT_INT32
            elif arr.dtype.kind in "iu":
                arr, code = arr.astype(np.int64), _lib.GAMUT_INT64
            elif arr.dtype == np.float64:
                code = _lib.GAMUT_FLOAT64
            else:
                raise GamutError("E18", f"{path}: model data holds booleans, int32, int64 and "
                                         f"float64 arrays, not {arr.dtype}")
            arr = np.ascontiguousarray(arr)
            shape = (ctypes.c_int64 * arr.ndim)(*arr.shape)
            call("gamut_tree_set_array", h, b(path), code, arr.ctypes.data_as(ctypes.c_void_p),
                 arr.size, arr.ndim, shape)


def _from_tree(h: ctypes.c_void_p, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in _lib.strings_out("gamut_tree_keys", h, b(prefix)):
        path = f"{prefix}/{key}" if prefix else key
        kind = ctypes.c_int()
        call("gamut_tree_kind", h, b(path), ctypes.byref(kind))
        k = kind.value
        if k == 0:
            out[key] = None
        elif k in (1, 2, 3):
            i, f = ctypes.c_int64(), ctypes.c_double()
            call("gamut_tree_scalar", h, b(path), ctypes.byref(i), ctypes.byref(f))
            out[key] = bool(i.value) if k == 1 else (i.value if k == 2 else f.value)
        elif k == 4:
            out[key] = _lib.strings_out("gamut_tree_strings", h, b(path))[0]
        elif k == 6:
            out[key] = _lib.strings_out("gamut_tree_strings", h, b(path))
        elif k == 7:
            out[key] = _from_tree(h, path)
        else:
            dtype, rank = ctypes.c_int(), ctypes.c_int()
            shape = (ctypes.c_int64 * 8)()
            call("gamut_tree_array_info", h, b(path), ctypes.byref(dtype), ctypes.byref(rank), shape,
                 len(shape))
            np_dtype = {_lib.GAMUT_INT8: np.int8, _lib.GAMUT_INT32: np.int32,
                        _lib.GAMUT_INT64: np.int64, _lib.GAMUT_FLOAT64: np.float64}[dtype.value]
            arr = np.empty(tuple(shape[i] for i in range(rank.value)), dtype=np_dtype)
            call("gamut_tree_array", h, b(path), arr.ctypes.data_as(ctypes.c_void_p), arr.nbytes)
            out[key] = arr.astype(bool) if dtype.value == _lib.GAMUT_INT8 else arr
    return out


# --- the plug-in interface ------------------------------------------------------

_REGISTRY: dict[str, type] = {}


def register_model_type(cls: type) -> type:
    """Registers a model type, so that `evaluate` runs the files that name
    it; usable as a decorator. A file records the type's name and its
    numbers, never its code, so every program that evaluates the file
    registers the type first. `create_model` shows the whole pattern.

    The class has (SPEC.md section 7.3):

    type         its name in files; name it after your project:
                 "mylab.polynomial".
    load(numbers)  a classmethod: the model from the dictionary `save`
                 returned.
    save()       the model's numbers: a dictionary of numbers, text,
                 booleans, NumPy arrays of booleans, int32, int64 or
                 float64, and dictionaries of those.
    call(inputs, wanted)  inputs maps each input the model reads to an
                 array with a value per row. wanted lists what to return,
                 each item one of (output, "values"), (output, "std"),
                 (output, "quantile", q) or (output, "derivative", name).
                 Returns {output: {"values": ..., "std": ...,
                 "quantiles": {q: ...}, "derivatives": {name: ...}}} with
                 what was wanted: a value per row for a scalar, rows x
                 nodes (or cells) for a field."""
    name = getattr(cls, "type", None)
    if not isinstance(name, str) or not name:
        raise GamutError("", "a model type has a class attribute `type`, its name")
    for method in ("load", "call", "save"):
        if not callable(getattr(cls, method, None)):
            raise GamutError("", f"a model type provides {method}")
    _REGISTRY[name] = cls
    return cls


def _nearest_check(numbers: Mapping[str, Any]) -> None:
    handle = _to_tree(numbers)
    try:
        call("gamut_nearest_check", handle)
    finally:
        _lib._lib.gamut_tree_free(handle)


class Nearest:
    """The built-in model: for each input row, the outputs of the closest
    stored point (spec section 7.5).  Evaluated by the core, so every
    language gets the same answers."""

    type = "nearest"

    def __init__(self, columns: Sequence[str], lower: Sequence[float], upper: Sequence[float],
                 x: Any, outputs: Mapping[str, Any]) -> None:
        self.columns = [str(c) for c in columns]
        self.lower = np.asarray(lower, dtype=np.float64)
        self.upper = np.asarray(upper, dtype=np.float64)
        self.x = np.asarray(x, dtype=np.float64).reshape(-1, len(self.columns))
        self.outputs = {k: np.asarray(v, dtype=np.float64) for k, v in outputs.items()}
        _nearest_check(self.save())

    @classmethod
    def load(cls, numbers: Mapping[str, Any]) -> "Nearest":
        """The model from its stored numbers (spec section 7.5)."""
        # Numbers from a file are checked before any is looked up: a damaged
        # or foreign file may lack one (E17).
        _nearest_check(numbers)
        return cls(numbers["columns"], numbers["lower"], numbers["upper"], numbers["x"],
                   numbers["outputs"])

    def save(self) -> dict[str, Any]:
        """Its numbers, to store."""
        return {"columns": list(self.columns), "lower": self.lower, "upper": self.upper,
                "x": self.x, "outputs": dict(self.outputs)}

    def call(self, inputs: Mapping[str, Any], wanted: Sequence[tuple]) -> dict[str, dict]:
        """For each input row, the values of the closest stored point."""
        missing = [c for c in self.columns if c not in inputs]
        if missing:
            raise GamutError("", f"nearest needs the inputs {', '.join(missing)}")
        cols = [np.ascontiguousarray(np.asarray(inputs[c], dtype=np.float64)) for c in self.columns]
        n = len(cols[0]) if cols else len(next(iter(inputs.values()))) if inputs else 0
        handle = _to_tree(self.save())
        try:
            names = _lib.string_array(self.columns)
            ptrs = (ctypes.POINTER(ctypes.c_double) * len(cols))(
                *[c.ctypes.data_as(ctypes.POINTER(ctypes.c_double)) for c in cols])
            lengths = (ctypes.c_int64 * len(cols))(*[c.size for c in cols])
            out: dict[str, dict] = {}
            for output, kind, *extra in wanted:
                if kind != "values":
                    raise GamutError("", f"nearest gives values only, not {kind}")
                per = ctypes.c_int64()
                call("gamut_nearest_output_size", handle, b(output), ctypes.byref(per))
                values = np.empty(n * per.value, dtype=np.float64)
                call("gamut_nearest_call", handle, names, ptrs, lengths, len(cols), n, b(output),
                     values.ctypes.data_as(ctypes.POINTER(ctypes.c_double)), values.size)
                shape = self.outputs[output].shape[1:]
                out.setdefault(output, {})["values"] = values.reshape((n,) + shape)
            return out
        finally:
            _lib._lib.gamut_tree_free(handle)


register_model_type(Nearest)


# --- writing model files ---------------------------------------------------------


class ModelFile(Study):
    """A model file open to write: declarations, then `add_model`."""

    def add_model(self, id: str, model: Any, inputs: Sequence[str], repr: str | None = None) -> None:
        """Stores a model: `id` is the name the results give as their
        "model"; `model` an object of a registered type, or `Nearest`;
        `inputs` the parameters, labels or "coordinates" it reads. The file
        keeps the numbers `model.save()` returns; `repr` is an optional
        one-line description."""
        numbers = model.save()
        if not isinstance(numbers, Mapping):
            raise GamutError("E18", f"{id}: save() gave {type(numbers).__name__}; it returns a "
                                     "dictionary of model data")
        handle = _to_tree(numbers)
        try:
            names = list(inputs)
            call("gamut_add_model", self._handle(), b(id), b(model.type), _lib.string_array(names),
                 len(names), handle, b(repr or ""))
        finally:
            _lib._lib.gamut_tree_free(handle)


def create_model(path: str, *, writer: str, parameters: Mapping[str, Any] | None = None,
                 labels: Mapping[str, Any] | None = None, scalars: Mapping[str, Any] | None = None,
                 fields: Mapping[str, Any] | None = None, constants: Mapping[str, Any] | None = None,
                 mesh: str | None = None, per: str = "fixed",
                 coordinates: Mapping[str, Any] | None = None,
                 trained_on: Sequence[str] | None = None, title: str | None = None,
                 license: str | None = None, references: str | None = None,
                 source: str | None = None, portion_marking: str | None = None) -> ModelFile:
    """Creates a model file and returns it open to add models: use it in a
    `with` block, or call `close()`. The destination must not exist.
    A model file holds no runs. It is
    declared as `create` declares a data file (labels, constants, mesh,
    per, coordinates, title, license, references, source,
    portion_marking), except:

    - `parameters`: each needs "lower" and "upper", the range the model
      was fitted on, as
      `{"alpha": {"units": "degree", "lower": 0.0, "upper": 10.0}}`.
      `evaluate` warns (W4) of an input outside it, and evaluates it.
    - `scalars`, `fields`: each names the model and the output that
      computes it, as `{"cl": {"units": "1", "model": "fit", "output": "cl"}}`.
      A spread or a derivative is declared as in `create` ("of",
      "statistic", "with_respect_to"), and the model's `call` is asked for
      it.
    - `trained_on`: the file_id (`study.describe()["file_id"]`) of each
      study the model was fitted on.
    - `portion_marking`: a marking the model's author set, as free text;
      `evaluate` copies it into every answer file.

    Then `add_model(id, model, inputs)` stores each model: an object of a
    type registered with `register_model_type`, or the built-in `Nearest`.
    The file keeps the numbers its `save` returns, never code; a program
    that evaluates the file registers the type first. Closing refuses a
    file with no model, or a result whose model was never added.

    The whole pattern, with a model type of one's own:

        import numpy as np
        import gamut

        @gamut.register_model_type
        class Polynomial:
            type = "example.polynomial"        # the name the file records

            def __init__(self, coefficients):
                self.coefficients = np.asarray(coefficients, dtype=float)

            @classmethod
            def load(cls, numbers):            # numbers: the dictionary save returned
                return cls(numbers["coefficients"])

            def save(self):                    # numbers, text, booleans, arrays, dictionaries
                return {"coefficients": self.coefficients}

            def call(self, inputs, wanted):    # an array per input, a value per row
                (x,) = inputs.values()
                return {output: {"values": np.polyval(self.coefficients, x)}
                        for output, *_ in wanted}

        alpha = np.array([0.0, 2.0, 4.0, 6.0])
        with gamut.create_model("lift.gamut", writer="my fit",
                                parameters={"alpha": {"units": "degree", "lower": 0.0, "upper": 6.0}},
                                scalars={"cl": {"units": "1", "model": "fit", "output": "cl"}}) as model:
            model.add_model("fit", Polynomial(np.polyfit(alpha, 0.11 * alpha, 2)), inputs=["alpha"])

        with gamut.evaluate("lift.gamut", {"alpha": [1.0, 5.0]}) as answer:   # an ordinary data file
            print(answer.get_scalar("cl"))
    """
    axes = _axes(coordinates)        # before the file exists: a refusal leaves none
    handle = ctypes.c_void_p()
    call("gamut_create_model", b(path), b(writer), b(mesh or ""), b(per), ctypes.byref(handle))
    study = ModelFile(handle, path, writing=True)
    study._mesh_kind, study._per = mesh or "", per if mesh else ""
    study._axes = axes
    try:
        for key, value in (("title", title), ("license", license), ("references", references),
                           ("source", source), ("portion_marking", portion_marking)):
            if value is not None:
                call("gamut_set_attribute", handle, b(key), b(value))
        if trained_on:
            call("gamut_set_attribute", handle, b("trained_on"), b(" ".join(trained_on)))
        for name, value in (labels or {}).items():
            spec = _label_spec(value)
            cats = list(spec.get("categories", []))
            call("gamut_declare_label", handle, b(name), b(spec.get("role", "categorical")),
                 _lib.string_array(cats), len(cats))
        for name, value in (parameters or {}).items():
            spec = _spec(value, "units")
            has = "lower" in spec or "upper" in spec
            call("gamut_declare_parameter", handle, b(name), b(spec.get("role", "design")),
                 b(spec.get("units")), _precision(spec.get("dtype")), 1 if has else 0,
                 float(spec.get("lower", math.nan)), float(spec.get("upper", math.nan)),
                 b(spec.get("run_group", "")))
        if coordinates is not None:
            call("gamut_declare_coordinates", handle, b(coordinates.get("units")),
                 _precision(coordinates.get("precision")), int(coordinates.get("axes", 3)),
                 b(coordinates.get("model", "")), b(coordinates.get("output", "")))

        def declare(name: str, spec: dict, where: str) -> None:
            q = spec.get("q")
            call("gamut_declare_result", handle, b(name), b(where), b(spec.get("units")),
                 _precision(spec.get("precision")), b(spec.get("of", "")),
                 b(spec.get("statistic", "")), 0 if q is None else 1, float(q or 0.0),
                 b(spec.get("method", "")), b(spec.get("with_respect_to", "")),
                 b(spec.get("axis", "")), b(spec.get("vector", "")), -1,
                 b(spec.get("model", "")), b(spec.get("output", "")))

        for name, value in (scalars or {}).items():
            declare(name, dict(value), "scalar")
        for name, value in (fields or {}).items():
            spec = dict(value)
            declare(name, spec, spec.get("at", "node"))
        for name, value in (constants or {}).items():
            number, units = value
            if isinstance(number, np.ndarray) and number.ndim == 0:
                number = number[()]                     # its NumPy scalar
            if isinstance(number, np.float32):
                call("gamut_set_constant", handle, b(name), b(units), _lib.GAMUT_FLOAT32, float(number), 0)
            elif isinstance(number, (int, np.integer)) and not isinstance(number, (bool, np.bool_)):
                call("gamut_set_constant", handle, b(name), b(units), _lib.GAMUT_INT64, 0.0,
                     _lib.int64_value(number, name))
            else:
                call("gamut_set_constant", handle, b(name), b(units), _lib.GAMUT_FLOAT64,
                     float(number), 0)
    except BaseException:
        # A half-declared file is not wanted; the declaration error stands.
        study._abandon(remove=True)
        raise
    return study


# --- evaluation ---------------------------------------------------------------------


class _Temporary(Study):
    """An evaluated file in memory: a temporary file removed on close."""

    def __init__(self, handle, path, directory):
        super().__init__(handle, path, writing=False)
        self._directory = directory

    def close(self) -> None:
        super().close()
        self._directory.cleanup()


def _input(ev: ctypes.c_void_p, name: str) -> np.ndarray:
    """An input as a model reads it, from the evaluation."""
    code, rank = ctypes.c_int(), ctypes.c_int()
    shape = (ctypes.c_int64 * 3)()
    call("gamut_evaluation_input_info", ev, b(name), ctypes.byref(code), ctypes.byref(rank), shape, 3)
    out = np.empty(tuple(shape[: rank.value]), dtype=np.int64 if code.value == _lib.GAMUT_INT64 else np.float64)
    call("gamut_evaluation_input", ev, b(name), out.ctypes.data_as(ctypes.c_void_p), out.nbytes)
    return out


def _run(m: Study, ev: ctypes.c_void_p, model_id: str) -> None:
    """Calls one model of a registered type with what it reads, and gives the
    evaluation each answer it is asked for."""
    d = _declared(m, f"models/{model_id}")
    cls = _REGISTRY.get(d["type"])
    if cls is None:
        raise GamutError("", f"the model {model_id} is of type {d['type']!r}, whose software is not "
                              "registered here (register_model_type)")
    model = cls.load(m.model_numbers(model_id))
    given = {k: _input(ev, k) for k in d["inputs"].split()}
    outputs, kinds, keys = _lib.lists_out("gamut_evaluation_requests", 3, ev, b(model_id))
    wanted = [(o, "quantile", float(y)) if k == "quantile" else (o, k, y) if k == "derivative" else (o, k)
              for o, k, y in zip(outputs, kinds, keys)]
    result = model.call(given, wanted)
    for (o, k, y), ask in zip(zip(outputs, kinds, keys), wanted):
        record = result.get(o)
        if record is None:
            raise GamutError("", f"the model {model_id} gave no output {o}")
        if k == "values":
            values = record.get("values")
        elif k == "std":
            values = record.get("std")
        elif k == "quantile":
            values = record.get("quantiles", {}).get(ask[2])
        else:
            values = record.get("derivatives", {}).get(y)
        if values is None:
            raise GamutError("", f"the model {model_id} gave no {k} for {o}")
        flat = _lib.as_array(values).ravel()      # as given: the core converts it as written values
        call("gamut_evaluation_answer", ev, b(model_id), b(o), b(k), b(y), _lib.dtype_code(flat),
             flat.ctypes.data_as(ctypes.c_void_p), flat.size)


def evaluate(model_path: str, inputs: Mapping[str, Any], path: str | None = None,
             coordinates: Any = None) -> Study:
    """Evaluates a model file on a table of inputs (spec section 7.4) and
    returns the resulting data file, open to read. An explicit `path` must
    not exist. `inputs` maps each
    parameter to values and each label to names from the model file's
    table, all of one length; `coordinates` (rows x nodes x axes) when a
    model reads geometry the file does not store.  Each model's type must
    be registered (`register_model_type`; `Nearest` is built in).  An
    input outside a parameter's bounds is evaluated, with a warning (W4),
    and the answer's `outside(name)` says how far each row lies outside.
    Without `path` the data file is temporary and removed when closed:
    read it in a `with` block, or give `path` to keep it."""
    with _open(model_path) as m:
        labels, params = set(m.names("labels")), set(m.names("parameters"))
        n = len(np.atleast_1d(np.asarray(next(iter(inputs.values()))))) if inputs else 0
        # The core checks the inputs, runs the built-in models and writes the
        # answer; this layer converts values and calls the registered types.
        out_path, temporary, directory = path, path is None, None
        if temporary:
            directory = tempfile.TemporaryDirectory(prefix="gamut-evaluate-")
            out_path = os.path.join(directory.name, "result.gamut")
        ev = ctypes.c_void_p()
        try:
            call("gamut_evaluation_begin", m._handle(), n, b(out_path), ctypes.byref(ev))
            for name, given in inputs.items():
                if name in labels:
                    names = [str(x) for x in np.atleast_1d(np.asarray(given))]
                    call("gamut_evaluation_names", ev, b(name), _lib.string_array(names), len(names))
                elif name not in params:          # the core says what it is not
                    call("gamut_evaluation_values", ev, b(name), _lib.GAMUT_FLOAT64, None, 0)
                else:
                    int64 = m.describe(name).get("dtype") == "int64"
                    col = np.ascontiguousarray(np.atleast_1d(
                        _lib.int64_exactly(given, name) if int64 else _lib.float64_exactly(given, name)))
                    call("gamut_evaluation_values", ev, b(name), _lib.dtype_code(col),
                         col.ctypes.data_as(ctypes.c_void_p), col.size)
            if coordinates is not None:
                pts = np.ascontiguousarray(_lib.float64_exactly(coordinates, "coordinates"))
                call("gamut_evaluation_coordinates", ev, _lib.GAMUT_FLOAT64,
                     pts.ctypes.data_as(ctypes.c_void_p), pts.size)
            found, models = _lib.lists_out("gamut_evaluation_ready", 2, ev)
            for finding in found:
                warnings.warn(finding, stacklevel=2)
            for model_id in models:
                _run(m, ev, model_id)
            call("gamut_evaluation_finish", ev)
        except BaseException:
            if directory is not None:
                directory.cleanup()
            raise
        finally:
            _lib._lib.gamut_evaluation_free(ev)
    if temporary:
        handle = ctypes.c_void_p()
        call("gamut_open", b(out_path), ctypes.byref(handle))
        return _Temporary(handle, out_path, directory)
    return _open(out_path)

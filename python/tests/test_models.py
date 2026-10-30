"""Model files, the plug-in interface and evaluation, end to end."""

from __future__ import annotations

import numpy as np
import pytest

import gamut


def reference_nearest(x, lower, upper, q):
    """Spec section 7.5 written out in plain Python, term by term."""
    out = []
    for row in q:
        best, best_i = float("inf"), -1
        for i, point in enumerate(x):
            d = 0.0
            for j in range(len(row)):
                span = upper[j] - lower[j]
                if span == 0.0:
                    continue
                t = (row[j] - point[j]) / span
                d = d + t * t
            if d < best:
                best, best_i = d, i
        out.append(best_i)
    return out


def test_portion_marking_is_copied_into_every_answer(tmp_path):
    """Spec section 7.4: the answer carries the model file's marking; a model
    file without one gives an answer without one."""
    marked, plain = str(tmp_path / "marked.gamut"), str(tmp_path / "plain.gamut")
    marking = "Example marking \u2014 for the study team only"      # free text, UTF-8
    for path, mark in ((marked, marking), (plain, None)):
        with gamut.create_model(path, writer="t", portion_marking=mark,
                                 parameters={"x": {"units": "1", "lower": 0, "upper": 1}},
                                 scalars={"y": {"units": "1", "model": "fit", "output": "y"}}) as mf:
            mf.add_model("fit", gamut.Nearest(["x"], [0.0], [1.0], [[0.1], [0.9]], {"y": [1.0, 2.0]}),
                         ["x"])
        assert not gamut.validate(path).findings
    with gamut.open(marked) as f:
        assert f.describe()["portion_marking"] == marking
    with gamut.open(plain) as f:
        assert "portion_marking" not in f.describe()
    out = str(tmp_path / "answer.gamut")
    with gamut.evaluate(marked, {"x": [0.2, 0.8]}, path=out) as a:
        assert a.describe()["portion_marking"] == marking
        assert a.get_scalar("y").tolist() == [1.0, 2.0]
    assert not gamut.validate(out).findings
    with gamut.evaluate(plain, {"x": [0.2]}) as a:
        assert "portion_marking" not in a.describe()


def test_nearest_model_file_and_evaluation(tmp_path):
    mp = str(tmp_path / "cl_model.gamut")
    pts = np.array([[0.0], [1.0], [2.0]])
    x = np.array([[0.3, 0.0], [0.6, 4.0], [0.3, 4.0], [0.6, 0.0]])
    model = gamut.Nearest(["mach", "alpha"], [0.3, 0.0], [0.6, 4.0], x,
                           {"cl": [0.0, 0.5, 0.4, 0.1],
                            "p": [[1, 1, 1], [2, 2, 2], [3, 3, 3], [4, 4, 4]]})
    with gamut.create_model(mp, writer="Proximant", mesh="shared", per="fixed",
                             coordinates={"units": "m", "axes": 1},
                             parameters={"mach": {"units": "1", "role": "condition", "lower": 0.3, "upper": 0.6},
                                         "alpha": {"units": "degree", "role": "condition", "lower": 0.0, "upper": 4.0}},
                             scalars={"cl": {"units": "1", "model": "fit", "output": "cl"}},
                             fields={"p": {"units": "Pa", "at": "node", "model": "fit", "output": "p"}},
                             trained_on=["0000-training-file"]) as f:
        f.set_mesh(pts)
        f.add_model("fit", model, inputs=["mach", "alpha"], repr="nearest of 4 runs")
    assert gamut.validate(mp).findings == ()
    with gamut.open(mp) as f:
        assert f.kind == "model" and f.row_count == 0
        assert f.describe("models/fit")["type"] == "nearest"
        assert f.describe()["trained_on"] == "0000-training-file"
        file_id = f.describe()["file_id"]
    inputs = {"mach": [0.31, 0.58, 0.45], "alpha": [3.9, 0.2, 2.0]}
    out_path = str(tmp_path / "pred.gamut")
    with gamut.evaluate(mp, inputs, path=out_path) as pred:
        idx = reference_nearest(x, [0.3, 0.0], [0.6, 4.0], np.column_stack(list(inputs.values())))
        np.testing.assert_array_equal(pred.get_scalar("cl"), np.array([0.0, 0.5, 0.4, 0.1])[idx])
        np.testing.assert_array_equal(pred.get_field("p")[:, 0], np.array([1, 2, 3, 4.0])[idx])
        assert pred.describe()["evaluated_from"] == file_id
        np.testing.assert_array_equal(pred.get_points(), pts)
    assert gamut.validate(out_path).findings == ()
    with gamut.evaluate(mp, {"mach": [], "alpha": []}) as none:
        assert none.row_count == 0 and none.get_scalar("cl").shape == (0,)
    # An output of the wrong width is refused with no rows as with some.
    wide = str(tmp_path / "wide.gamut")
    with gamut.create_model(wide, writer="t", parameters={"x": {"units": "1", "lower": 0, "upper": 1}},
                             scalars={"y": {"units": "1", "model": "fit", "output": "y"}}) as mf:
        mf.add_model("fit", gamut.Nearest(["x"], [0.0], [1.0], [[0.0], [1.0]], {"y": [[10, 11], [20, 21]]}),
                     ["x"])
    for x in ([0.5], []):
        with pytest.raises(gamut.GamutError, match="2 values per row, not 1"):
            gamut.evaluate(wide, {"x": x})
    # In memory: a temporary file that disappears on close.
    p = gamut.evaluate(mp, inputs)
    path = p.path
    assert p.row_count == 3
    p.close()
    import os
    assert not os.path.exists(path)


def test_nearest_matches_the_written_out_rule_exactly():
    rng = np.random.default_rng(3)
    x = rng.random((200, 3))
    lower, upper = [0.0, 0.0, 0.5], [1.0, 1.0, 0.5]   # a fixed column is left out
    m = gamut.Nearest(["a", "b", "c"], lower, upper, x, {"i": np.arange(200.0)})
    q = rng.random((300, 3))
    got = m.call({"a": q[:, 0], "b": q[:, 1], "c": q[:, 2]}, [("i", "values")])["i"]["values"]
    assert got.astype(int).tolist() == reference_nearest(x, lower, upper, q)
    nan = m.call({"a": [np.nan], "b": [0.5], "c": [0.5]}, [("i", "values")])["i"]["values"]
    assert np.isnan(nan[0])
    # The core reads one value per row from each input, so unequal or
    # missing inputs are refused first.
    with pytest.raises(gamut.GamutError, match="300 values of every input"):
        m.call({"a": q[:, 0], "b": q[:, 1], "c": q[:5, 2]}, [("i", "values")])
    with pytest.raises(gamut.GamutError, match="needs the inputs c"):
        m.call({"a": q[:, 0], "b": q[:, 1]}, [("i", "values")])


@gamut.register_model_type
class Line:
    """A model type of a user's own: y = a * x + b with a constant spread."""

    type = "tests.line"

    def __init__(self, a, b, sigma):
        self.a, self.b, self.sigma = a, b, sigma

    @classmethod
    def load(cls, numbers):
        return cls(numbers["a"], numbers["b"], numbers["sigma"])

    def save(self):
        return {"a": self.a, "b": self.b, "sigma": self.sigma, "note": None}

    def call(self, inputs, wanted):
        x = np.asarray(inputs["x"], dtype=float)
        y = self.a * x + self.b
        record = {"values": y, "std": np.full_like(y, self.sigma),
                  "quantiles": {0.025: y - 1.96 * self.sigma, 0.975: y + 1.96 * self.sigma},
                  "derivatives": {"x": np.full_like(y, self.a)}}
        return {"y": record}


def test_plug_in_with_std_quantiles_and_derivatives(tmp_path):
    mp = str(tmp_path / "line.gamut")
    with gamut.create_model(mp, writer="tests",
                             parameters={"x": {"units": "m", "lower": 0.0, "upper": 10.0}},
                             scalars={"y": {"units": "1", "model": "line", "output": "y"},
                                      "y_std": {"units": "1", "model": "line", "output": "y", "of": "y", "statistic": "std"},
                                      "y_lo": {"units": "1", "model": "line", "output": "y", "of": "y",
                                               "statistic": "quantile", "q": 0.025},
                                      "dy_dx": {"units": "m-1", "model": "line", "output": "y", "of": "y",
                                                "with_respect_to": "x"}}) as f:
        f.add_model("line", Line(2.0, 1.0, 0.1), inputs=["x"])
    assert gamut.validate(mp).findings == ()
    with pytest.warns(UserWarning, match="W4"):
        pred = gamut.evaluate(mp, {"x": [1.0, 2.0, 11.0]})
    with pred:
        np.testing.assert_allclose(pred.get_scalar("y"), [3.0, 5.0, 23.0])
        np.testing.assert_allclose(pred.get_scalar("y_std"), [0.1] * 3)
        np.testing.assert_allclose(pred.get_scalar("y_lo"), [3.0 - 0.196, 5.0 - 0.196, 23.0 - 0.196])
        np.testing.assert_allclose(pred.get_scalar("dy_dx"), [2.0] * 3)
        assert pred.related("y")["quantiles"] == {0.025: "y_lo"}


def test_refusals(tmp_path):
    mp = str(tmp_path / "bad.gamut")
    with pytest.raises(gamut.GamutError) as e:
        gamut.create_model(mp, writer="t", parameters={"x": "m"})
    assert e.value.rule == "E16"
    with pytest.raises(gamut.GamutError) as e:
        with gamut.create_model(mp, writer="t", parameters={"x": {"units": "m", "lower": 0, "upper": 1}},
                                 scalars={"y": {"units": "1", "model": "missing", "output": "y"}}):
            pass
    assert e.value.rule in ("E16", "E17")
    # A model whose software is not registered can be read but not evaluated.
    mp2 = str(tmp_path / "foreign.gamut")

    class Foreign:
        type = "elsewhere.secret"

        def save(self):
            return {"w": np.zeros(3)}

    with gamut.create_model(mp2, writer="t", parameters={"x": {"units": "m", "lower": 0, "upper": 1}},
                             scalars={"y": {"units": "1", "model": "m", "output": "y"}}) as f:
        f.add_model("m", Foreign(), inputs=["x"])
    with pytest.raises(gamut.GamutError, match="not registered"):
        gamut.evaluate(mp2, {"x": [0.5]})
    # What save returns must be a dictionary of data: anything else is named
    # as such, a ragged list is refused, and a float32 array (as model
    # weights often are) is refused by its dtype.
    for numbers, says in (({"w": object()}, "w: object is not model data"),
                          (object(), "save\\(\\) gave object"),
                          ([1.0], "save\\(\\) gave list"),
                          ({"w": [[1], [2, 3]]}, "w: not an array of model data"),
                          ({"w": [1.0, "a"]}, "w: text is stored as one list"),
                          ({"w": [["a"], ["b"]]}, "w: text is stored as one list"),
                          ({"w": np.zeros(2, np.float32)}, "not float32")):
        Foreign.save = lambda self, numbers=numbers: numbers
        with pytest.raises(gamut.GamutError, match=says) as e:
            with gamut.create_model(str(tmp_path / "data.gamut"), writer="t",
                                     parameters={"x": {"units": "m", "lower": 0, "upper": 1}},
                                     scalars={"y": {"units": "1", "model": "m", "output": "y"}}) as f:
                f.add_model("m", Foreign(), inputs=["x"])
        assert e.value.rule == "E18"
    # A nearest model whose bounds differ from its parameters' is refused.
    mp3 = str(tmp_path / "bounds.gamut")
    with pytest.raises(gamut.GamutError) as e:
        with gamut.create_model(mp3, writer="t", parameters={"x": {"units": "m", "lower": 0, "upper": 1}},
                                 scalars={"y": {"units": "1", "model": "n", "output": "y"}}) as f:
            f.add_model("n", gamut.Nearest(["x"], [0.0], [2.0], [[0.0]], {"y": [1.0]}), inputs=["x"])
    assert e.value.rule == "E17"


@gamut.register_model_type
class Stretch:
    """A model of the geometry itself: a triangle stretched along x by s."""

    type = "tests.stretch"

    def __init__(self, base):
        self.base = np.asarray(base, dtype=float)

    @classmethod
    def load(cls, numbers):
        return cls(numbers["base"])

    def save(self):
        return {"base": self.base}

    def call(self, inputs, wanted):
        s = np.asarray(inputs["s"], dtype=float)
        pts = np.repeat(self.base[None], len(s), axis=0)
        pts[:, :, 0] *= s[:, None]
        return {"coordinates": {"values": pts}}


def test_a_model_computes_the_coordinates(tmp_path):
    mp = str(tmp_path / "shape.gamut")
    base = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    with gamut.create_model(mp, writer="tests", mesh="shared", per="run",
                             coordinates={"units": "m", "axes": 3, "model": "shape",
                                          "output": "coordinates"},
                             parameters={"s": {"units": "1", "lower": 1.0, "upper": 3.0}}) as f:
        f.set_mesh(cells=([5], [0, 3], [0, 1, 2]), n_nodes=3)
        f.add_model("shape", Stretch(base), inputs=["s"])
    assert gamut.validate(mp).findings == ()
    with gamut.open(mp) as f:
        d = f.describe("coordinates")
        assert (d["model"], d["output"]) == ("shape", "coordinates")
    # The validator holds the coordinates' model to the rules a result's is.
    import shutil
    import h5py
    for rule, edit in (("E17", lambda a: a.modify("model", np.bytes_(b"nothing"))),
                       ("E17", lambda a: a.__delitem__("output")),
                       ("E16", lambda a: (a.__delitem__("model"), a.__delitem__("output")))):
        bad = str(tmp_path / "bad.gamut")
        shutil.copy(mp, bad)
        with h5py.File(bad, "r+") as h:
            edit(h["mesh/coordinates"].attrs)
        assert rule in {f.rule for f in gamut.validate(bad).errors}
    # The writer refuses a computing model without its output.
    with pytest.raises(gamut.GamutError, match="E17"):
        gamut.create_model(str(tmp_path / "no_output.gamut"), writer="tests", mesh="shared",
                           per="run", coordinates={"units": "m", "axes": 3, "model": "shape"},
                           parameters={"s": {"units": "1", "lower": 1.0, "upper": 3.0}})
    # A copy keeps which model computes the coordinates.
    cp = str(tmp_path / "copy.gamut")
    gamut.write_copy(mp, cp)
    with gamut.open(cp) as f:
        assert f.describe("coordinates")["model"] == "shape"
    with gamut.evaluate(mp, {"s": [1.0, 2.5]}) as pred:
        np.testing.assert_array_equal(pred.get_points(0), base)
        np.testing.assert_array_equal(pred.get_points(1)[:, 0], [0.0, 2.5, 0.0])


def test_model_numbers_read_back_without_the_type_registered(tmp_path):
    mp = str(tmp_path / "line.gamut")
    with gamut.create_model(mp, writer="tests",
                             parameters={"x": {"units": "m", "lower": 0.0, "upper": 10.0}},
                             scalars={"y": {"units": "1", "model": "line", "output": "y"}}) as f:
        f.add_model("line", Line(2.0, 1.0, 0.1), inputs=["x"])
    with gamut.open(mp) as f:
        assert f.model_numbers("line") == Line(2.0, 1.0, 0.1).save()
        with pytest.raises(gamut.GamutError):
            f.model_numbers("missing")
    registered = gamut._models._REGISTRY.pop("tests.line")
    try:
        with gamut.open(mp) as f:
            assert f.model_numbers("line")["a"] == 2.0
    finally:
        gamut._models._REGISTRY["tests.line"] = registered


@gamut.register_model_type
class Short:
    """A model that returns one value too few."""

    type = "tests.short"

    @classmethod
    def load(cls, numbers):
        return cls()

    def save(self):
        return {"k": 1}

    def call(self, inputs, wanted):
        return {"y": {"values": np.zeros(len(inputs["x"]) - 1)}}


def test_a_failed_evaluation_leaves_no_file(tmp_path):
    import os
    mp = str(tmp_path / "short.gamut")
    with gamut.create_model(mp, writer="tests",
                             parameters={"x": {"units": "m", "lower": 0.0, "upper": 10.0}},
                             scalars={"y": {"units": "1", "model": "short", "output": "y"}}) as m:
        m.add_model("short", Short(), ["x"])
    out = str(tmp_path / "out.gamut")
    with pytest.raises(gamut.GamutError):
        gamut.evaluate(mp, {"x": [1.0, 2.0]}, path=out)
    assert not os.path.exists(out)
    import tempfile
    before = set(os.listdir(tempfile.gettempdir()))
    with pytest.raises(gamut.GamutError):
        gamut.evaluate(mp, {"x": [1.0, 2.0]})
    assert {f for f in set(os.listdir(tempfile.gettempdir())) - before if f.endswith(".gamut")} == set()
    # Refused while the new file is being declared, before any model runs.
    import h5py
    with h5py.File(mp, "r+") as f:
        del f["x"].attrs["units"]
    with pytest.raises(gamut.GamutError) as e:
        gamut.evaluate(mp, {"x": [1.0]}, path=out)
    assert e.value.rule == "E7"
    assert not os.path.exists(out)
    with pytest.raises(gamut.GamutError):
        gamut.evaluate(mp, {"x": [1.0]})
    assert {f for f in set(os.listdir(tempfile.gettempdir())) - before if f.endswith(".gamut")} == set()


def test_one_bound_is_refused(tmp_path):
    """Neither bound is taken as 0 when only the other is given."""
    for i, bound in enumerate(({"lower": 0.0}, {"upper": 1.0})):
        for create in (gamut.create, gamut.create_model):
            with pytest.raises(gamut.GamutError) as e:
                create(str(tmp_path / f"{create.__name__}{i}.gamut"), writer="tests",
                       parameters={"x": {"units": "1", **bound}})
            assert e.value.rule == "E16" and "give both bounds" in e.value.message


def test_a_model_file_declares_a_bool_label_as_a_data_file_does(tmp_path):
    mp = str(tmp_path / "flag.gamut")
    with gamut.create_model(mp, writer="tests", labels={"on": bool},
                             parameters={"x": {"units": "m", "lower": 0.0, "upper": 1.0}},
                             scalars={"y": {"units": "1", "model": "m", "output": "y"}}) as m:
        m.add_model("m", gamut.Nearest(["x"], [0.0], [1.0], [[0.0], [1.0]], {"y": [0.0, 1.0]}), ["x"])
    with gamut.open(mp) as f:
        assert f.categories("on") == ["false", "true"]


def test_outside_measures_each_row_against_the_bounds(tmp_path):
    """Zero inside and on a bound, value - lower below, value - upper above,
    NaN for a missing value; a parameter without bounds is refused, not
    reported as inside."""
    import h5py
    p = str(tmp_path / "bounded.gamut")
    with gamut.create(p, writer="tests",
                       parameters={"x": {"units": "m", "lower": 0.0, "upper": 1.0},
                                   "n": {"units": "1", "lower": 2, "upper": 4}, "mach": "1"},
                       scalars={"cl": "1"}) as s:
        s.add_runs({"x": [-0.5, 0.0, 0.25, 1.0, 1.5, 0.5], "n": [1, 2, 3, 4, 5, 6],
                    "mach": [0.5] * 6, "cl": [0.0] * 6})
    with h5py.File(p, "r+") as f:       # the writer never stores a missing parameter (E5)
        f["x"][5] = np.nan
    with gamut.open(p) as s:
        np.testing.assert_array_equal(s.outside("x"), [-0.5, 0.0, 0.0, 0.0, 0.5, np.nan])
        np.testing.assert_array_equal(s.outside("x", rows=[0, 4]), [-0.5, 0.5])
        np.testing.assert_array_equal(s.outside("x", rows=slice(1, 4)), [0.0, 0.0, 0.0])
        assert s.outside("x", rows=4) == 0.5
        assert s.outside("x", rows=[]).shape == (0,)
        np.testing.assert_array_equal(s.outside("n"), [-1.0, 0.0, 0.0, 0.0, 1.0, 2.0])
        with pytest.raises(gamut.GamutError, match="mach declares no bounds"):
            s.outside("mach")
        with pytest.raises(gamut.GamutError, match='no parameter "cl"'):
            s.outside("cl")
        with pytest.raises(gamut.GamutError, match='nothing is called "y"'):
            s.outside("y")
        for rows, says in (([6], "outside the 6 positions"), ([3, 1], "strictly increasing"),
                           ([1.5], "positions are integers")):
            with pytest.raises(gamut.GamutError, match=says):
                s.outside("x", rows=rows)


def test_an_answer_marks_the_inputs_outside_the_fitted_range(tmp_path):
    """The answer of evaluate keeps the model's bounds: each row says which
    input lies outside the range the model was fitted on, and how far."""
    mp = str(tmp_path / "lift.gamut")
    with gamut.create_model(mp, writer="tests",
                             parameters={"mach": {"units": "1", "lower": 0.25, "upper": 0.75},
                                         "alpha": {"units": "degree", "lower": 0.0, "upper": 4.0}},
                             scalars={"cl": {"units": "1", "model": "fit", "output": "cl"}}) as m:
        m.add_model("fit", gamut.Nearest(["mach", "alpha"], [0.25, 0.0], [0.75, 4.0],
                                         [[0.25, 0.0], [0.75, 4.0]], {"cl": [0.0, 1.0]}),
                    inputs=["mach", "alpha"])
    out = str(tmp_path / "answer.gamut")
    with pytest.warns(UserWarning, match="W4"):
        answer = gamut.evaluate(mp, {"mach": [0.125, 0.5, 0.75], "alpha": [2.0, 5.5, -1.0]}, path=out)
    with answer:
        np.testing.assert_array_equal(answer.outside("mach"), [-0.125, 0.0, 0.0])
        np.testing.assert_array_equal(answer.outside("alpha"), [0.0, 1.5, -1.0])
    assert gamut.validate(out).warning_ids == ["W4"]


@gamut.register_model_type
class Echo:
    """Gives back x as y, and the first node's x coordinate as x0."""

    type = "tests.echo"

    @classmethod
    def load(cls, numbers):
        return cls()

    def save(self):
        return {"k": 1}

    def call(self, inputs, wanted):
        out = {}
        for output, *_ in wanted:
            if output == "x0":
                out[output] = {"values": np.asarray(inputs["coordinates"])[:, 0, 0]}
            else:
                out[output] = {"values": np.asarray(inputs["x"], dtype=float)}
        return out


def test_an_int64_input_past_2_53_is_evaluated_as_an_integer(tmp_path):
    # Bounds are compared exactly, and the nearest model takes int64 as
    # float64 (spec section 7.5), so a large integer is neither refused nor
    # misjudged against its bounds.
    big = 2**53 + 1
    mp = str(tmp_path / "big.gamut")
    with gamut.create_model(mp, writer="tests",
                             parameters={"x": {"units": "1", "dtype": "int64", "lower": 0.0, "upper": float(2**53)}},
                             scalars={"y": {"units": "1", "model": "echo", "output": "y"},
                                      "z": {"units": "1", "model": "n", "output": "z"}}) as m:
        m.add_model("echo", Echo(), ["x"])
        m.add_model("n", gamut.Nearest(["x"], [0.0], [float(2**53)], [[0.0], [float(2**53)]], {"z": [1.0, 2.0]}),
                    ["x"])
    with pytest.warns(UserWarning, match="x is outside the model's domain .* in 1 of 2 rows"):
        out = gamut.evaluate(mp, {"x": [big, 2**53]})
    with out:
        assert out.get_parameter("x").tolist() == [big, 2**53]
        assert out.get_scalar("z").tolist() == [2.0, 2.0]
        assert out.outside("x").tolist() == [1.0, 0.0]


def _echo_model(path, per="fixed"):
    with gamut.create_model(path, writer="tests", mesh="shared", per=per,
                             coordinates={"units": "m", "axes": 2},
                             parameters={"x": {"units": "1", "lower": 0.0, "upper": 2.0}},
                             scalars={"x0": {"units": "m", "model": "echo", "output": "x0"}}) as m:
        m.set_mesh(np.array([[1.0, 0.0], [0.0, 1.0]]), cells=([3], [0, 2], [0, 1]))
        m.add_model("echo", Echo(), ["x", "coordinates"])


def test_given_coordinates_are_the_answers_per_run(tmp_path):
    # Spec section 7.4: coordinates the caller gives are the data file's,
    # per run, though the model file's are fixed.
    mp = str(tmp_path / "echo.gamut")
    _echo_model(mp)
    given = np.array([[[10.0, 0.0], [0.0, 1.0]], [[50.0, 0.0], [0.0, 1.0]]])
    with gamut.evaluate(mp, {"x": [1.0, 2.0]}, coordinates=given) as out:
        assert out.describe()["per"] == "run"
        assert out.get_scalar("x0").tolist() == [10.0, 50.0]
        np.testing.assert_array_equal(out.get_points(1), given[1])
    # Without them, the stored ones, fixed; and for no rows, no rows.
    with gamut.evaluate(mp, {"x": [1.0]}) as out:
        assert out.describe()["per"] == "fixed" and out.get_scalar("x0").tolist() == [1.0]
    with gamut.evaluate(mp, {"x": []}) as out:
        assert out.row_count == 0


def test_one_output_read_at_two_widths_is_refused(tmp_path):
    # A scalar and a node field, or a scalar and the coordinates, cannot
    # both be one model output: refused whatever the number of rows.
    cases = {"field": dict(per="fixed", coordinates={"units": "m", "axes": 1},
                           fields={"f": {"units": "1", "at": "node", "model": "fit", "output": "same"}}),
             "coordinates": dict(per="run", coordinates={"units": "m", "axes": 1, "model": "fit", "output": "same"})}
    for case, kw in cases.items():
        path = str(tmp_path / f"{case}.gamut")
        with gamut.create_model(path, writer="t", mesh="shared",
                                 parameters={"x": {"units": "1", "lower": 0.0, "upper": 1.0}},
                                 scalars={"s": {"units": "1", "model": "fit", "output": "same"}}, **kw) as m:
            if case == "field":
                m.set_mesh(np.array([[0.0], [1.0]]))
            else:
                m.set_mesh(n_nodes=2)
            m.add_model("fit", gamut.Nearest(["x"], [0.0], [1.0], [[0.0], [1.0]], {"same": [10.0, 20.0]}), ["x"])
        for x in ([0.5], []):
            with pytest.raises(gamut.GamutError, match="is read with 1 and with 2 values per row"):
                gamut.evaluate(path, {"x": x})


@gamut.register_model_type
class Complex:
    """A model that answers with complex numbers."""

    type = "tests.complex"

    @classmethod
    def load(cls, numbers):
        return cls()

    def save(self):
        return {"k": 1}

    def call(self, inputs, wanted):
        return {"y": {"values": np.array([1 + 2j] * len(inputs["x"]))}}


def test_an_answer_or_input_that_is_not_real_is_refused(tmp_path):
    # A complex, boolean or text value is refused, not cast (which would
    # drop an imaginary part with only a NumPy warning).
    mp = str(tmp_path / "complex.gamut")
    with gamut.create_model(mp, writer="t", parameters={"x": {"units": "1", "lower": 0.0, "upper": 1.0}},
                             scalars={"y": {"units": "1", "model": "c", "output": "y"}}) as m:
        m.add_model("c", Complex(), ["x"])
    for given in ({"x": [0.5]}, {"x": [0.5 + 1j]}, {"x": [True]}):
        with pytest.raises(gamut.GamutError, match="not real numbers") as e:
            gamut.evaluate(mp, given)
        assert e.value.rule == "E4"

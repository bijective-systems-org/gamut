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

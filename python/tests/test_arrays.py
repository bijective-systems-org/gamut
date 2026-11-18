"""Arrays (spec section 3.9): a fixed number of values per run, as data and as
a model's input, end to end through the Python layer."""

from __future__ import annotations

import warnings

import numpy as np
import pytest

import gamut


def wall_study(path, **extra):
    return gamut.create(path, writer="t", parameters={"mach": "1"},
                        arrays={"wall": {"units": "K", "length": 3, "role": "condition",
                                         "lower": 200.0, "upper": 400.0},
                                "plies": {"units": "1", "length": 2, "dtype": "int64"}},
                        scalars={"q": "W m-2"}, **extra)


def test_an_array_is_written_and_read_by_run_and_by_value(tmp_path):
    path = str(tmp_path / "a.gamut")
    with wall_study(path) as s:
        assert s.add_run({"mach": 0.5, "wall": [300.0, 310.0, 320.0], "plies": [4, 5], "q": 1.0}) == 0
        assert s.add_runs({"mach": [0.6, 0.7], "wall": np.array([[330, 340, 350], [150, 300, 450.0]]),
                           "plies": np.array([[6, 7], [8, 9]]), "q": [2.0, 3.0]}) == [1, 2]
    with gamut.open(path) as s:
        assert s.names("arrays") == ["plies", "wall"]
        assert s.names("parameters") == ["mach"]
        d = s.describe("wall")
        assert (d["kind"], d["role"], d["units"], d["length"], d["dtype"]) == \
            ("array", "condition", "K", "3", "float64")
        assert s.describe("plies")["role"] == "design"           # the default
        np.testing.assert_array_equal(s.get_array("wall"),
                                      [[300, 310, 320], [330, 340, 350], [150, 300, 450]])
        np.testing.assert_array_equal(s.get_array("wall", 2), [150, 300, 450])
        np.testing.assert_array_equal(s.get_array("wall", values=[0, 2]),
                                      [[300, 320], [330, 350], [150, 450]])
        np.testing.assert_array_equal(s.get_array("wall", slice(1, 3), slice(1, None)),
                                      [[340, 350], [300, 450]])
        plies = s.get_array("plies")
        assert plies.dtype == np.int64 and plies.tolist() == [[4, 5], [6, 7], [8, 9]]
        np.testing.assert_array_equal(s.outside("wall"), [[0, 0, 0], [0, 0, 0], [-50, 0, 50]])
        np.testing.assert_array_equal(s.outside("wall", 2), [-50, 0, 50])
        # The run table is one value per run: an array comes only when named.
        assert set(s.table()) == {"mach", "q"}
        assert s.table(["wall"])["wall"].shape == (3, 3)
        with pytest.raises(gamut.GamutError, match="is an array"):
            s.select("wall > 300")
    report = gamut.validate(path)
    assert report.ok and [(f.rule, f.path) for f in report.findings] == [("W4", "wall")]


def test_array_values_are_checked_before_anything_is_written(tmp_path):
    path = str(tmp_path / "a.gamut")
    with wall_study(path) as s:
        base = {"mach": 0.5, "wall": [300.0, 310.0, 320.0], "plies": [4, 5], "q": 1.0}
        with pytest.raises(gamut.GamutError, match="E5") as e:
            s.add_run({**base, "wall": [300.0, 310.0]})
        assert "give 3 per run" in str(e.value)
        with pytest.raises(gamut.GamutError, match="never missing"):
            s.add_run({**base, "wall": [300.0, float("nan"), 320.0]})
        with pytest.raises(gamut.GamutError, match="E4"):
            s.add_run({**base, "plies": [4.5, 5.0]})                  # counts are whole numbers
        with pytest.raises(gamut.GamutError, match="E2"):
            s.add_run({k: v for k, v in base.items() if k != "wall"})
        # Runs x length, not length x runs.
        with pytest.raises(gamut.GamutError, match="E5"):
            s.add_runs({"mach": [0.5, 0.6], "wall": np.full((3, 2), 300.0),
                        "plies": np.zeros((2, 2), dtype=np.int64), "q": [1.0, 2.0]})
        s.add_run(base)
    with gamut.open(path) as s:
        assert s.row_count == 1


def test_array_declarations_are_refused_by_rule(tmp_path):
    def declared(**arrays):
        with gamut.create(str(tmp_path / "d.gamut"), writer="t", arrays=arrays):
            pass

    with pytest.raises(gamut.GamutError, match="E5"):
        declared(a={"units": "1"})                                     # no length
    with pytest.raises(gamut.GamutError, match="never a time"):
        declared(a={"units": "s", "length": 2, "role": "time"})
    with pytest.raises(gamut.GamutError, match="E8"):
        declared(gamut_a={"units": "1", "length": 2})
    with pytest.raises(gamut.GamutError, match="E16"):
        declared(a={"units": "1", "length": 2, "lower": 0.0})
    with pytest.raises(gamut.GamutError, match="E4"):
        declared(a={"units": "1", "length": 2, "dtype": "float32"})
    with pytest.raises(gamut.GamutError, match="E16"):
        with gamut.create_model(str(tmp_path / "m.gamut"), writer="t",
                                arrays={"a": {"units": "1", "length": 2}}):
            pass


def test_an_array_converts_its_units_as_a_whole(tmp_path):
    pytest.importorskip("pint")
    path = str(tmp_path / "a.gamut")
    with gamut.create(path, writer="t", arrays={"wall": {"units": "K", "length": 2}}) as s:
        s.add_run({"wall": ([26.85, 126.85], "degC")})
    with gamut.open(path) as s:
        np.testing.assert_allclose(s.get_array("wall", 0), [300.0, 400.0])
        np.testing.assert_allclose(s.get_array("wall", 0, units="degC"), [26.85, 126.85])


def test_append_extract_and_copy_keep_arrays(tmp_path):
    path, part, copy = (str(tmp_path / n) for n in ("a.gamut", "p.gamut", "c.gamut"))
    with wall_study(path) as s:
        s.add_runs({"mach": [0.5, 0.6], "wall": [[300, 310, 320], [330, 340, 350]],
                    "plies": [[1, 2], [3, 4]], "q": [1.0, 2.0]})
    with gamut.open(path, "a") as s:
        s.add_run({"mach": 0.7, "wall": [360, 370, 380], "plies": [5, 6], "q": 3.0})
    gamut.extract(path, part, [0, 2])
    gamut.write_copy(path, copy)
    assert gamut.append(copy, part) == 2
    with gamut.open(copy) as s:
        assert s.get_row_ids().tolist() == [0, 1, 2, 3, 4]
        np.testing.assert_array_equal(s.get_array("wall")[3:], [[300, 310, 320], [360, 370, 380]])
    for p in (path, part, copy):
        assert gamut.validate(p).ok
    # Another length is another declaration.
    other = str(tmp_path / "o.gamut")
    with gamut.create(other, writer="t", parameters={"mach": "1"},
                      arrays={"wall": {"units": "K", "length": 4, "role": "condition"},
                              "plies": {"units": "1", "length": 2, "dtype": "int64"}},
                      scalars={"q": "W m-2"}):
        pass
    with pytest.raises(gamut.GamutError, match="the array wall"):
        gamut.append(path, other)


def nearest_model(path):
    nn = gamut.Nearest(["mach", "wall"], [0.0, 200.0], [1.0, 400.0],
                       [[0.5, 300.0, 300.0, 300.0], [0.5, 400.0, 400.0, 400.0]],
                       {"q": [1.0, 2.0]}, widths=[1, 3])
    with gamut.create_model(path, writer="t", parameters={"mach": {"units": "1", "lower": 0, "upper": 1}},
                            arrays={"wall": {"units": "K", "length": 3, "lower": 200.0, "upper": 400.0,
                                             "role": "condition"}},
                            scalars={"q": {"units": "1", "model": "nn", "output": "q"}}) as f:
        f.add_model("nn", nn, ["mach", "wall"])


def test_nearest_reads_an_array_value_by_value(tmp_path):
    path = str(tmp_path / "m.gamut")
    nearest_model(path)
    assert gamut.validate(path).ok
    with gamut.open(path) as m:
        assert m.model_numbers("nn")["widths"].tolist() == [1, 3]
    wall = np.array([[310.0, 310.0, 310.0], [390.0, 390.0, 500.0], [350.0, 360.0, 370.0]])
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with gamut.evaluate(path, {"mach": [0.5, 0.5, 0.5], "wall": wall}) as r:
            # Distance summed over every value, each scaled by its input's bounds.
            np.testing.assert_array_equal(r.get_scalar("q"), [1.0, 2.0, 2.0])
            np.testing.assert_array_equal(r.get_array("wall"), wall)
            np.testing.assert_array_equal(r.outside("wall")[1], [0, 0, 100])
            assert r.describe("wall")["upper"] == m_upper(path)
    assert [str(w.message) for w in caught] == \
        ["W4: wall is outside the model's domain [200, 400] in 1 of 3 rows (1 value)"]
    with pytest.raises(gamut.GamutError, match="first axis"):     # length x rows
        gamut.evaluate(path, {"mach": [0.5, 0.5], "wall": np.full((3, 2), 300.0)})


def m_upper(path):
    with gamut.open(path) as m:
        return m.describe("wall")["upper"]


def test_a_nearest_model_states_each_input_width(tmp_path):
    path = str(tmp_path / "m.gamut")
    with pytest.raises(gamut.GamutError, match="x is points x columns"):
        gamut.Nearest(["mach", "wall"], [0, 200], [1, 400], [[0.5, 300.0]], {"q": [1.0]}, widths=[1, 3])
    with gamut.create_model(path, writer="t", parameters={"mach": {"units": "1", "lower": 0, "upper": 1}},
                            arrays={"wall": {"units": "K", "length": 3, "lower": 200.0, "upper": 400.0}},
                            scalars={"q": {"units": "1", "model": "nn", "output": "q"}}) as f:
        wrong = gamut.Nearest(["mach", "wall"], [0, 200], [1, 400], [[0.5, 300.0, 1.0, 2.0]], {"q": [1.0]},
                              widths=[2, 2])
        with pytest.raises(gamut.GamutError, match="E17"):
            f.add_model("nn", wrong, ["mach", "wall"])
        f.add_model("nn", gamut.Nearest(["mach", "wall"], [0, 200], [1, 400], [[0.5, 300, 300, 300]],
                                        {"q": [1.0]}, widths=[1, 3]), ["mach", "wall"])


class Summing:
    """A model of a registered type that reads an array as rows x length."""

    type = "test-summing"

    def __init__(self, scale):
        self.scale = scale

    @classmethod
    def load(cls, numbers):
        return cls(numbers["scale"])

    def save(self):
        return {"scale": self.scale}

    def call(self, inputs, wanted):
        counts = inputs["plies"]
        assert counts.dtype == np.int64 and counts.ndim == 2
        return {"total": {"values": self.scale * counts.sum(axis=1).astype(np.float64)}}


def test_a_registered_model_reads_an_int64_array_exactly(tmp_path):
    gamut.register_model_type(Summing)
    path = str(tmp_path / "m.gamut")
    big = 2**53 + 1                 # not a float64: kept and compared as an integer
    with gamut.create_model(path, writer="t",
                            arrays={"plies": {"units": "1", "length": 2, "dtype": "int64",
                                              "lower": 0, "upper": 2**53}},
                            scalars={"total": {"units": "1", "model": "sum", "output": "total"}}) as f:
        f.add_model("sum", Summing(1.0), ["plies"])
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with gamut.evaluate(path, {"plies": np.array([[1, 2], [3, big]], dtype=np.int64)}) as r:
            assert r.get_array("plies").tolist() == [[1, 2], [3, big]]
            np.testing.assert_array_equal(r.get_scalar("total")[0], 3.0)
    assert [str(w.message) for w in caught] == \
        ["W4: plies is outside the model's domain [0, 9.0072e+15] in 1 of 2 rows (1 value)"]

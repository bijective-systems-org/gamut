"""Every leaf of section 17, out of a file and back into one.

The corpus cases each exercise a part of the dictionary codec. This
is the whole of it in one file: nested dictionaries including an
empty one, a nested dictionary using `type` and `repr` as keys,
float64 arrays of two and three dimensions, int32 and int64 arrays, a
boolean array, an array holding NaN and both infinities, an empty
float64 array, an empty two-dimensional int64 array, a list of
strings, an empty fixed-length string dataset, an integer, a float of
the same value, both booleans, a string, an empty string, the null
sentinel, the most negative int64 and the smallest subnormal float64.

The source is built here with h5py against sections 17, 18, 21 and 25
directly, so that it comes from no implementation, and with the expected tagged
form of section 30 stated beside it rather than computed. The
callable's `type` is one nothing registers, so the reader keeps the
dictionary whole rather than interpreting it.

Two things are asserted: reading the file gives the reference
exactly, and
writing it again gives a file structurally equal to the source. An
empty fixed-length string dataset is the leaf that made the
difference, because a bare Python list carries no element type and
section 25 gives "an empty list with no element type known" the empty
float64 dataset.
"""

from __future__ import annotations

import shutil

import h5py
import numpy as np

from mestra import _v0 as mestra
from tests import corpus

DIM_NAME = "This is a netCDF dimension but not a netCDF variable."


def _sdtype(nbytes: int):
    return h5py.string_dtype(encoding="utf-8", length=max(1, nbytes))


def _sattr(obj, name: str, value: str) -> None:
    _rattr(obj, name, value.encode("utf-8"))


def _rattr(obj, name: str, raw: bytes) -> None:
    n = max(1, len(raw))
    obj.attrs.create(name, raw.ljust(n, b"\0"), dtype=_sdtype(n))


def _scale(group, name: str, length: int, unlimited: bool = False):
    dset = group.create_dataset(
        name, shape=(length,), dtype=">f4", track_times=False,
        maxshape=(None,) if unlimited else None,
        chunks=(1,) if unlimited else ((length,) if length else (1,)))
    _sattr(dset, "CLASS", "DIMENSION_SCALE")
    _sattr(dset, "NAME", "%s%10d" % (DIM_NAME, length))
    return dset


def _array(group, name: str, data) -> None:
    data = np.asarray(data)
    empty = 0 in data.shape
    dset = group.create_dataset(
        name, shape=data.shape, dtype=data.dtype.newbyteorder("<"),
        data=data, track_times=False,
        maxshape=tuple(None if n == 0 else n for n in data.shape)
        if empty else None,
        chunks=(1,) * data.ndim if empty else None)
    for axis, length in enumerate(data.shape):
        _array_scale(group, dset, name, axis, int(length))


def _array_scale(group, dset, name: str, axis: int, length: int) -> None:
    scale = _scale(group, "mestra_%s_d%d" % (name, axis), length,
                   unlimited=(length == 0))
    dset.dims[axis].attach_scale(scale)


def _strings(group, name: str, values,
             size: int | None = None) -> None:
    raw = [v.encode("utf-8") for v in values]
    n = size if size is not None else max([len(r) for r in raw] + [1])
    empty = not raw
    dset = group.create_dataset(
        name, shape=(len(raw),), dtype=_sdtype(n),
        data=[r.ljust(n, b"\0") for r in raw] if raw else None,
        track_times=False, maxshape=(None,) if empty else None,
        chunks=(1,) if empty else None)
    _array_scale(group, dset, name, 0, len(raw))


def build_source(path: str) -> str:
    """The corpus case `affine_zero_rows` with a dictionary of
    every leaf of section 17 in place of its callable."""
    shutil.copy(corpus.case_path("affine_zero_rows"), path)
    with h5py.File(path, "r+") as f:
        del f["callables"]["m1"]
        g = f.create_group("callables/m1")
        _sattr(g, "type", "verify_all")
        _sattr(g, "repr", "every leaf of section 17")

        # One scalar per attribute encoding of section 18. An integer
        # and a float that happen to be equal stay different.
        g.attrs.create("an_int", np.int64(7))
        g.attrs.create("a_float", np.float64(7.0))
        g.attrs.create("a_true", np.int8(1))
        g.attrs.create("a_false", np.int8(0))
        _sattr(g, "a_string", "a plain ascii string")
        _sattr(g, "an_empty_string", "")
        _rattr(g, "a_null", b"\x00null")
        g.attrs.create("a_negative", np.int64(-9223372036854775807))
        g.attrs.create("a_tiny_float", np.float64(5e-324))

        _array(g, "floats_2d", np.array([[1.5, -2.5, 3.0],
                                         [4.25, 5.0, 6.125]]))
        _array(g, "floats_3d", np.arange(24, dtype="<f8").reshape(2, 3, 4))
        _array(g, "ints64_1d", np.array([1, 2, 3], dtype="<i8"))
        _array(g, "ints32_2d", np.array([[10, 20], [30, 40]], dtype="<i4"))
        _array(g, "bools_1d", np.array([1, 0, 1], dtype="<i1"))
        _array(g, "nonfinite", np.array([np.nan, np.inf, -np.inf, 0.0]))
        _array(g, "empty_f64", np.zeros((0,), dtype="<f8"))
        _array(g, "empty_i64_2d", np.zeros((0, 3), dtype="<i8"))
        _strings(g, "list_of_strings", ["mach", "alpha", "beta"])
        _strings(g, "empty_strings", [], size=1)

        nest = g.create_group("nest")
        nest.attrs.create("depth", np.int64(1))
        _array(nest, "values", np.array([0.5, 1.5], dtype="<f8"))
        deeper = nest.create_group("deeper")
        _sattr(deeper, "type", "not the callable type")
        _sattr(deeper, "repr", "not the callable repr")
        deeper.attrs.create("depth", np.int64(2))
        g.create_group("an_empty_dict")
    return path


def _f64(x) -> str:
    return "%.17e" % float(x)


#: The tagged form of section 30, from the specification and not from
#: any implementation.
REFERENCE = {
    "t": "dict",
    "v": {
        "a_false": {"t": "bool", "v": False},
        "a_float": {"t": "f64", "v": _f64(7.0)},
        "a_negative": {"t": "i64", "v": -9223372036854775807},
        "a_null": {"t": "null"},
        "a_string": {"t": "str", "v": "a plain ascii string"},
        "a_tiny_float": {"t": "f64", "v": _f64(5e-324)},
        "a_true": {"t": "bool", "v": True},
        "an_empty_dict": {"t": "dict", "v": {}},
        "an_empty_string": {"t": "str", "v": ""},
        "an_int": {"t": "i64", "v": 7},
        "bools_1d": {"t": "array", "dtype": "bool", "shape": [3],
                     "data": [True, False, True]},
        "empty_f64": {"t": "array", "dtype": "float64", "shape": [0],
                      "data": []},
        "empty_i64_2d": {"t": "array", "dtype": "int64", "shape": [0, 3],
                         "data": []},
        "empty_strings": {"t": "strings", "shape": [0], "data": []},
        "floats_2d": {"t": "array", "dtype": "float64", "shape": [2, 3],
                      "data": [_f64(x) for x in
                               [1.5, -2.5, 3.0, 4.25, 5.0, 6.125]]},
        "floats_3d": {"t": "array", "dtype": "float64", "shape": [2, 3, 4],
                      "data": [_f64(x) for x in range(24)]},
        "ints32_2d": {"t": "array", "dtype": "int32", "shape": [2, 2],
                      "data": [10, 20, 30, 40]},
        "ints64_1d": {"t": "array", "dtype": "int64", "shape": [3],
                      "data": [1, 2, 3]},
        "list_of_strings": {"t": "strings", "shape": [3],
                            "data": ["mach", "alpha", "beta"]},
        "nest": {"t": "dict", "v": {
            "deeper": {"t": "dict", "v": {
                "depth": {"t": "i64", "v": 2},
                "repr": {"t": "str", "v": "not the callable repr"},
                "type": {"t": "str", "v": "not the callable type"}}},
            "depth": {"t": "i64", "v": 1},
            "values": {"t": "array", "dtype": "float64", "shape": [2],
                       "data": [_f64(0.5), _f64(1.5)]}}},
        "nonfinite": {"t": "array", "dtype": "float64", "shape": [4],
                      "data": ["nan", "inf", "-inf", _f64(0.0)]},
    },
}


def _dump(path: str):
    with mestra.read(path) as ds:
        callable_ = ds.callables["m1"]
        assert callable_.type == "verify_all"
        return corpus.tagged(callable_.to_dict())


def test_every_leaf_reads_as_the_specification_states(tmp_path):
    source = build_source(str(tmp_path / "source.mes"))
    assert corpus.same_tagged(_dump(source), REFERENCE) == []


def test_every_leaf_survives_a_round_trip(tmp_path):
    """Every leaf of the codec survives a write and a read.

    An empty fixed-length string dataset is the leaf that used to
    come back as an empty float64 dataset, because the reader handed
    back a bare Python list and the writer had nothing to go on.
    """
    source = build_source(str(tmp_path / "source.mes"))
    written = str(tmp_path / "written.mes")
    with mestra.read(source, lazy=False) as ds:
        mestra.write(ds, written)
    assert corpus.same_tagged(_dump(written), REFERENCE) == []
    assert corpus.structural_diff(source, written) == []


def test_the_empty_string_dataset_keeps_its_type(tmp_path):
    """Section 25 by itself: the two empty lists are different
    values and stay different."""
    source = build_source(str(tmp_path / "source.mes"))
    written = str(tmp_path / "written.mes")
    with mestra.read(source, lazy=False) as ds:
        mestra.write(ds, written)
    with h5py.File(written, "r") as f:
        empty = f["/callables/m1/empty_strings"]
        assert h5py.check_string_dtype(empty.dtype) is not None
        assert h5py.check_string_dtype(empty.dtype).length == 1
        assert empty.shape == (0,)
        assert f["/callables/m1/empty_f64"].dtype == np.dtype("<f8")

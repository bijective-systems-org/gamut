"""Helpers for running the conformance corpus.

The corpus lives in vectors/ beside this package and is shared by
every implementation in every language. Nothing here is part of the
mestra package: it is the corpus's own conventions, from SPEC.md
section 30, written once so that the tests read plainly.
"""

from __future__ import annotations

import json
import os
from typing import Any

import h5py
import numpy as np
import pytest

from mestra._v0.model import NamedArray

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
VECTORS = os.path.join(ROOT, "vectors")
CASES = os.path.join(VECTORS, "cases")

#: Section 18: not part of this format, ignored wherever they appear.
MACHINERY = frozenset([
    "CLASS", "NAME", "DIMENSION_LIST", "REFERENCE_LIST",
    "DIMENSION_LABELS", "_Netcdf4Dimid", "_Netcdf4Coordinates",
    "_nc3_strict", "_NCProperties"])


def case_names() -> list[str]:
    """Every case of the corpus, in the manifest's order."""
    with open(os.path.join(VECTORS, "manifest.json"),
              encoding="utf-8") as fh:
        manifest = json.load(fh)
    return [case["name"] for case in manifest["cases"]]


#: The cases vectors/README.md generates on demand rather than
#: commits, because of their size. Their expected.json is committed
#: like every other one, so the manifest lists them either way.
ON_DEMAND = {"wide_keys": "--on-demand"}


def case_path(name: str) -> str:
    """The golden file of one case.

    A case that is generated on demand and has not been generated
    skips with the flag that writes it, rather than failing as a
    file that will not open.
    """
    path = os.path.join(CASES, name, "case.mes")
    if name in ON_DEMAND and not os.path.exists(path):
        pytest.skip("run: python vectors/generate.py %s"
                    % ON_DEMAND[name])
    return path


def expected(name: str) -> dict[str, Any]:
    with open(os.path.join(CASES, name, "expected.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


def valid_case_names() -> list[str]:
    """The cases a reader and a writer must handle end to end."""
    return [n for n in case_names()
            if not expected(n)["validator"]["errors"]]


# ---------------------------------------------------- numbers as text

def as_float(text: str) -> float:
    """Parse the decimal string of section 30 to a float64."""
    return float(text)


def bits_equal(a: Any, b: Any) -> bool:
    """Equal as float64 bits, so that NaN equals NaN."""
    x = np.float64(a)
    y = np.float64(b)
    return x.tobytes() == y.tobytes()


def fnum(value: Any) -> str:
    """A float64 as section 30 writes it."""
    value = float(value)
    if value != value:
        return "nan"
    if value == float("inf"):
        return "inf"
    if value == float("-inf"):
        return "-inf"
    return "%.17e" % value


# ------------------------------------------------------------- probes

#: The order a probe's indices are written in (section 30).
PROBE_AXES = ("row", "instance", "draw", "node", "component", "index")


def probe_value(dataset: Any, probe: dict[str, Any]) -> Any:
    """The value a probe names, found by axis name and never by
    axis position."""
    array = slot_array(dataset, probe["slot"])
    where = {name: probe[name] for name in PROBE_AXES if name in probe}
    if isinstance(array, NamedArray):
        if "node" in where and "node" not in array.dims:
            where["cell"] = where.pop("node")
        return array.at(**where)
    # A dataset inside a callable's dictionary has no logical
    # dimensions; its axes are the probe's own order.
    index = tuple(where[name] for name in PROBE_AXES if name in where)
    return np.asarray(array)[index]


def slot_array(dataset: Any, path: str) -> Any:
    """The array a probe's HDF5 path names, from the model."""
    parts = path.strip("/").split("/")
    if parts[0] == "keys":
        return dataset.keys[parts[1]].values
    if parts[0] == "scalars":
        return dataset.scalars[parts[1]].values
    if parts[0] == "row_support":
        return NamedArray(dataset.row_support, ("row",))
    if parts[0] == "supports":
        support = dataset.supports[parts[1]]
        if parts[2] == "coordinates":
            return support.coordinates.values
        if parts[2] == "cell_types":
            return NamedArray(support.cell_types, ("cell",))
        if parts[2] == "cell_offsets":
            return NamedArray(support.cell_offsets, ("cell_plus_one",))
        if parts[2] == "cell_connectivity":
            return NamedArray(support.cell_connectivity, ("index",))
        arrays = (support.node_arrays if parts[2] == "node_arrays"
                  else support.cell_arrays)
        return arrays[parts[3]].values
    if parts[0] == "callables":
        value: Any = dataset.callables[parts[1]].to_dict()
        for part in parts[2:]:
            value = value[part]
        return value
    raise KeyError(path)


# ------------------------------------------------- the tagged codec form

def tagged(value: Any) -> Any:
    """A dictionary value in the tagged form of section 30."""
    if value is None:
        return {"t": "null"}
    if isinstance(value, np.ndarray):
        if value.dtype.kind in ("U", "S", "O"):
            return {"t": "strings", "shape": list(value.shape),
                    "data": [str(v) for v in value.reshape(-1)]}
        if value.dtype == np.bool_:
            return {"t": "array", "dtype": "bool",
                    "shape": list(value.shape),
                    "data": [bool(v) for v in value.reshape(-1)]}
        if value.dtype == np.int32:
            return {"t": "array", "dtype": "int32",
                    "shape": list(value.shape),
                    "data": [int(v) for v in value.reshape(-1)]}
        if value.dtype == np.int64:
            return {"t": "array", "dtype": "int64",
                    "shape": list(value.shape),
                    "data": [int(v) for v in value.reshape(-1)]}
        return {"t": "array", "dtype": "float64",
                "shape": list(value.shape),
                "data": [fnum(v) for v in value.reshape(-1)]}
    if isinstance(value, dict):
        return {"t": "dict",
                "v": {k: tagged(value[k]) for k in sorted(value)}}
    if isinstance(value, list):
        if all(isinstance(v, str) for v in value):
            return {"t": "strings", "shape": [len(value)],
                    "data": list(value)}
        return tagged(np.asarray(value))
    if isinstance(value, (bool, np.bool_)):
        return {"t": "bool", "v": bool(value)}
    if isinstance(value, (int, np.integer)):
        return {"t": "i64", "v": int(value)}
    if isinstance(value, (float, np.floating)):
        return {"t": "f64", "v": fnum(value)}
    if isinstance(value, str):
        return {"t": "str", "v": value}
    raise TypeError("not representable: %r" % (value,))


def same_tagged(got: Any, want: Any) -> list[str]:
    """Where two tagged values differ, with floats compared as bits."""
    out: list[str] = []
    _compare_tagged(got, want, "", out)
    return out


def _compare_tagged(got: Any, want: Any, where: str,
                    out: list[str]) -> None:
    if not isinstance(got, dict) or got.get("t") != want.get("t"):
        out.append("%s: %r and %r" % (where or "/", got, want))
        return
    kind = want["t"]
    if kind == "dict":
        for key in sorted(set(got["v"]) | set(want["v"])):
            if key not in got["v"] or key not in want["v"]:
                out.append("%s/%s: on one side only" % (where, key))
                continue
            _compare_tagged(got["v"][key], want["v"][key],
                            "%s/%s" % (where, key), out)
        return
    if kind == "array":
        if got["dtype"] != want["dtype"] or got["shape"] != want["shape"]:
            out.append("%s: %s%r and %s%r"
                       % (where, got["dtype"], got["shape"],
                          want["dtype"], want["shape"]))
            return
        for at, (a, b) in enumerate(zip(got["data"], want["data"])):
            same = (bits_equal(as_float(a), as_float(b))
                    if want["dtype"] == "float64" else a == b)
            if not same:
                out.append("%s[%d]: %r and %r" % (where, at, a, b))
        return
    if kind == "f64":
        if not bits_equal(as_float(got["v"]), as_float(want["v"])):
            out.append("%s: %r and %r" % (where, got["v"], want["v"]))
        return
    if kind == "null":
        return
    if got.get("v") != want.get("v"):
        out.append("%s: %r and %r" % (where, got.get("v"),
                                      want.get("v")))


# --------------------------------------------- structural equality (30)

def structural_diff(left: str, right: str) -> list[str]:
    """The differences between two files under section 30.

    The same object paths; the same kind at each path; for a
    dataset, the same dtype including byte order, character set and
    padding, shape, maximum shape, chunk shape, filters and
    contents, floats compared as bits; the same attribute names and
    values, the machinery of section 18 excluded; and the same
    dimension scale attached to each axis, compared by name.
    """
    out: list[str] = []
    with h5py.File(left, "r") as a, h5py.File(right, "r") as b:
        first, second = _walk(a), _walk(b)
        for path in sorted(set(first) - set(second)):
            out.append("only in the first file: %s" % path)
        for path in sorted(set(second) - set(first)):
            out.append("only in the second file: %s" % path)
        for path in sorted(set(first) & set(second)):
            _compare_object(first[path], second[path], path, out)
    return out


def _walk(f: h5py.File) -> dict[str, Any]:
    paths = {"/": f}
    f.visititems(lambda name, obj: paths.__setitem__("/" + name, obj))
    return paths


def _compare_object(one: Any, two: Any, path: str,
                    out: list[str]) -> None:
    if isinstance(one, h5py.Dataset) != isinstance(two, h5py.Dataset):
        out.append("%s: a group in one file and a dataset in the other"
                   % path)
        return
    names_one = set(one.attrs) - MACHINERY
    names_two = set(two.attrs) - MACHINERY
    for name in sorted(names_one ^ names_two):
        out.append("%s: the attribute %s is on one side only"
                   % (path, name))
    for name in sorted(names_one & names_two):
        first = _attr_signature(one, name)
        second = _attr_signature(two, name)
        if first != second:
            out.append("%s: the attribute %s is %s and %s"
                       % (path, name, first, second))
    if not isinstance(one, h5py.Dataset):
        return
    for what, first, second in (
            ("dtype", _type_signature(one), _type_signature(two)),
            ("shape", one.shape, two.shape),
            ("maxshape", one.maxshape, two.maxshape),
            ("chunks", one.chunks, two.chunks),
            ("filters", _filters(one), _filters(two)),
            ("dimensions", _scale_names(one), _scale_names(two))):
        if first != second:
            out.append("%s: the %s is %r and %r"
                       % (path, what, first, second))
    if (one.shape == two.shape and one.dtype == two.dtype
            and not _values_equal(one[()], two[()])):
        out.append("%s: the contents differ" % path)


def _type_signature(dset: h5py.Dataset) -> str:
    kind = dset.id.get_type()
    if isinstance(kind, h5py.h5t.TypeStringID):
        return "string(size=%d,cset=%d,pad=%d)" % (
            kind.get_size(), kind.get_cset(), kind.get_strpad())
    return "%s/%s" % (dset.dtype.str, kind.get_order())


def _attr_signature(obj: Any, name: str) -> str:
    attr = obj.attrs.get_id(name)
    kind = attr.get_type()
    if isinstance(kind, h5py.h5t.TypeStringID):
        head = "string(size=%s,cset=%d,pad=%d)" % (
            "vlen" if kind.is_variable_str() else kind.get_size(),
            kind.get_cset(), kind.get_strpad())
    else:
        head = str(attr.dtype.str)
    value = obj.attrs[name]
    if isinstance(value, np.ndarray):
        value = value.tolist()
    if isinstance(value, bytes):
        value = repr(value)
    return "%s=%r" % (head, value)


def _filters(dset: h5py.Dataset) -> str:
    out = []
    if dset.shuffle:
        out.append("shuffle")
    if dset.compression is not None:
        out.append("%s:%s" % (dset.compression, dset.compression_opts))
    if dset.fletcher32:
        out.append("fletcher32")
    return ",".join(out)


def _scale_names(dset: h5py.Dataset) -> list[tuple[str, ...]]:
    return [tuple(dim[i].name.rsplit("/", 1)[-1]
                  for i in range(len(dim))) for dim in dset.dims]


def _values_equal(a: Any, b: Any) -> bool:
    a, b = np.asarray(a), np.asarray(b)
    if a.shape != b.shape or a.dtype != b.dtype:
        return False
    if a.dtype.kind == "f":
        return np.array_equal(a.view("u%d" % a.dtype.itemsize),
                              b.view("u%d" % b.dtype.itemsize))
    return bool(np.array_equal(a, b))

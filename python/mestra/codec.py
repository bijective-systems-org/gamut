"""The dictionary codec of SPEC.md sections 17 and 25.

A callable's dictionary maps to an HDF5 group so that every language
round-trips it identically: a nested dictionary is a subgroup, a
numeric array is a dataset with a dimension scale on each axis, and a
number, a boolean or a string is an attribute on the enclosing group.
A zero-dimensional array is written as the number it holds, because
no rule that preserved it as an array could round-trip in MATLAB and
C++ as well as in Python.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import h5py
import numpy as np

from . import h5safe, limits
from .encoding import (
    NULL_SENTINEL,
    decode_string,
    encode_strings,
    is_fixed_string,
    make_scale,
    nest,
    read_attr,
    string_dtype,
    write_attr,
    write_raw_string_attr,
)
from .errors import Finding, MestraError
from .names import RESERVED_PREFIX, is_legal_name

__all__ = ["encode_dict", "decode_dict", "ALLOWED_DTYPES", "RESERVED",
           "RESERVED_V0"]

#: Section 25: the dtypes a dictionary dataset may have.
ALLOWED_DTYPES = ("int8", "int32", "int64", "float64")

#: The names a callable's group holds as the container's own
#: attributes, so that a dictionary may not use them at its top level.
#: Version 1 adds `inputs` to the two version 0 reserved.
RESERVED = ("type", "repr", "inputs")
RESERVED_V0 = ("type", "repr")


def _sorted_keys(d: Mapping[str, Any]) -> list[str]:
    """Ascending order of the keys' UTF-8 bytes (section 25)."""
    return sorted((str(k) for k in d), key=lambda k: k.encode("utf-8"))


# ------------------------------------------------------------- writing

def encode_dict(group: h5py.Group, d: Mapping[str, Any],
                top_level: bool = True, depth: int = 0,
                reserved: tuple[str, ...] = RESERVED) -> None:
    """Write a dictionary into `group` (sections 17 and 25).

    A dictionary that nests deeper than `limits.MAX_DEPTH` is
    refused, because a reader of the file would refuse it too.
    """
    if depth > limits.MAX_DEPTH:
        raise MestraError(
            "E32", "a dictionary that nests more than %d groups deep "
            "is not representable" % limits.MAX_DEPTH, group.name)
    for key in _sorted_keys(d):
        value = d[key]
        if not is_legal_name(key):
            raise MestraError(
                "E33", "a dictionary key must be a legal netCDF-4 "
                "name", key)
        if key.startswith(RESERVED_PREFIX):
            raise MestraError(
                "E33", "a dictionary key must not begin with %s"
                % RESERVED_PREFIX, key)
        if top_level and key in reserved:
            raise MestraError(
                "E32", "%s are the container's attributes on the "
                "callable's group, so a dictionary may not use them at "
                "its top level" % ", ".join(reserved), key)
        _encode_value(group, key, value, depth)


def _encode_value(group: h5py.Group, key: str, value: Any,
                  depth: int = 0) -> None:
    if isinstance(value, Mapping):
        encode_dict(group.create_group(key), value, top_level=False,
                    depth=depth + 1)
        return
    if value is None:
        write_raw_string_attr(group, key, NULL_SENTINEL)
        return
    if isinstance(value, (bool, np.bool_, int, np.integer, float,
                          np.floating, str)):
        if isinstance(value, str) and "\x00" in value:
            raise MestraError(
                "E32", "a string holding a NUL byte is not "
                "representable", key)
        write_attr(group, key, value)
        return
    if isinstance(value, (list, tuple)):
        _encode_array(group, key, _list_to_array(key, list(value)))
        return
    if isinstance(value, np.ndarray):
        if value.ndim == 0:
            # Section 25: a zero-dimensional array is the number it
            # holds, written as an attribute.
            write_attr(group, key, value.reshape(-1)[0].item()
                       if value.dtype != np.int8
                       else bool(value.reshape(-1)[0]))
            return
        _encode_array(group, key, value)
        return
    raise MestraError(
        "E32", "a value of type %s is not representable"
        % type(value).__name__, key)


def _list_to_array(key: str, values: list[Any]) -> np.ndarray:
    """A list as section 25 allows it, or a refusal (E32)."""
    if not values:
        # An empty list with no element type known.
        return np.zeros((0,), dtype="<f8")
    if all(isinstance(v, str) for v in values):
        return np.array(values, dtype=np.str_)
    if any(isinstance(v, (Mapping, str)) or v is None for v in values):
        raise MestraError(
            "E32", "a list of dictionaries, a list mixing numbers and "
            "strings and a list of nulls are not representable", key)
    try:
        array = np.array(values)
    except ValueError:
        array = np.array(None, dtype=object)
    if array.dtype == object:
        raise MestraError(
            "E32", "a ragged or mixed nested list is not "
            "representable", key)
    return array


def _encode_array(group: h5py.Group, key: str, value: Any) -> None:
    array = np.asarray(value)
    if array.dtype.kind in "USO" or is_fixed_string(array.dtype):
        _encode_strings(group, key, array)
        return
    if array.dtype == np.bool_:
        array = array.astype("<i1")
    name = array.dtype.name
    if name == "int8":
        pass
    elif name not in ALLOWED_DTYPES:
        raise MestraError(
            "E32", "%s is not one of the dtypes a dictionary may hold "
            "(%s and fixed-length strings)"
            % (name, ", ".join(ALLOWED_DTYPES)), key)
    dset = _create(group, key, array, array.dtype.newbyteorder("<"),
                   array.shape)
    _attach_scales(group, key, dset, array.shape)


def _encode_strings(group: h5py.Group, key: str, array: Any) -> None:
    flat = [v.decode("utf-8") if isinstance(v, bytes) else str(v)
            for v in np.asarray(array).reshape(-1)]
    for value in flat:
        if "\x00" in value:
            raise MestraError(
                "E32", "a string holding a NUL byte is not "
                "representable", key)
    raw, size = encode_strings(flat)
    shape = tuple(int(n) for n in np.asarray(array).shape)
    dset = _create(group, key, nest(raw, shape), string_dtype(size),
                   shape)
    _attach_scales(group, key, dset, shape)


def _create(group: h5py.Group, key: str, data: Any, dtype: Any,
            shape: Any) -> h5py.Dataset:
    shape = tuple(int(n) for n in shape)
    empty = 0 in shape
    return group.create_dataset(
        key, shape=shape, dtype=dtype, data=data, track_times=False,
        # Section 25: every zero-length axis is created with an
        # unlimited maximum, so that the dimension is legal. An axis
        # that has a length keeps it, which is what the other three
        # writers produce and what the scale on that axis says.
        maxshape=tuple(None if n == 0 else n for n in shape)
        if empty else None,
        chunks=(1,) * len(shape) if empty else None)


def _attach_scales(group: h5py.Group, key: str, dset: h5py.Dataset,
                   shape: Any) -> None:
    for axis, length in enumerate(shape):
        scale = make_scale(group, "%s%s_d%d" % (RESERVED_PREFIX, key,
                                                axis),
                           int(length), unlimited=(length == 0))
        dset.dims[axis].attach_scale(scale)


# ------------------------------------------------------------- reading

def decode_dict(group: h5py.Group, top_level: bool = True,
                depth: int = 0,
                problems: list[Finding] | None = None,
                reserved: tuple[str, ...] = RESERVED
                ) -> dict[str, Any]:
    """Read back the dictionary stored in `group`.

    Every member and every attribute whose name begins with
    `mestra_` is skipped, and so are the machinery attributes of
    section 18. At the top level the names in `reserved` are the
    container's and are not entries of the dictionary.

    A dictionary is somebody else's data structure, so this walk
    follows no link, goes no deeper than `limits.MAX_DEPTH`, and
    reads no dataset larger than `limits.MAX_READ_ELEMENTS`. With
    `problems` given, what it could not read is appended there as a
    finding and the entry is left out; with `problems` left out, the
    first such thing is raised instead.
    """
    out: dict[str, Any] = {}
    if depth > limits.MAX_DEPTH:
        _trouble(problems, group.name, MestraError(
            "E41", "this dictionary nests more than %d groups deep, "
            "which this reader does not follow" % limits.MAX_DEPTH,
            group.name))
        return out
    for name in h5safe.attr_names(group):
        if name.startswith(RESERVED_PREFIX):
            continue
        if top_level and name in reserved:
            continue
        out[name] = read_attr(group, name)
    for member in h5safe.members(group):
        name = member.name
        if name.startswith(RESERVED_PREFIX):
            continue
        path = "%s/%s" % (group.name.rstrip("/"), name)
        if not member.usable:
            _trouble(problems, path, MestraError(
                member.rule, member.problem or "this member cannot be "
                                            "read", path))
            continue
        if isinstance(member.obj, h5py.Group):
            out[name] = decode_dict(member.obj, top_level=False,
                                    depth=depth + 1, problems=problems)
            continue
        try:
            out[name] = decode_array(member.obj, path)
        except MestraError as exc:
            _trouble(problems, path, exc)
    return out


def _trouble(problems: list[Finding] | None, where: str,
             exc: MestraError) -> None:
    """Collect a problem, or raise it when nobody is collecting."""
    if problems is None:
        raise exc
    problems.append(Finding(exc.rule, where, exc.message))


def decode_array(dset: h5py.Dataset, where: str = "") -> Any:
    """One dictionary dataset as the value it holds (section 25).

    Every value this returns carries its own element type, so that
    writing it again gives the same dataset. A numeric dataset is a
    numpy array, which carries its dtype. A one-dimensional string
    dataset is a list of `str`, whose elements carry the type -
    except when it is empty, where a bare Python list would carry
    nothing: section 25 makes "an empty list with no element type
    known" the empty float64 dataset, so an empty string dataset
    comes back as an empty numpy string array instead, which is the
    Python value for "an empty list of strings" and which the writer
    keeps as strings.
    """
    where = where or dset.name
    if dset.ndim == 0:
        raise MestraError(
            "E32", "a zero-dimensional dataset must be written as an "
            "attribute", where)
    values = h5safe.read_values(dset, where)
    if is_fixed_string(dset.dtype):
        flat = [decode_string(v) for v in np.asarray(values).reshape(-1)]
        if not flat:
            return np.empty(tuple(dset.shape), dtype="<U1")
        if dset.ndim == 1:
            return flat
        return np.array(flat, dtype=np.str_).reshape(dset.shape)
    array = np.asarray(values)
    if array.dtype == np.int8:
        # int8 means boolean inside a dictionary (section 25).
        return array.astype(bool)
    return array

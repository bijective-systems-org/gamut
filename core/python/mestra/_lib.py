"""The shared core, loaded with ctypes: the C interface of mestra.h and the
conversions every call needs.  Nothing here is public."""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

MES_AS_GIVEN = 0
MES_UINT8, MES_INT8, MES_INT32, MES_INT64, MES_FLOAT32, MES_FLOAT64 = 1, 2, 3, 4, 5, 6
SEL_ALL, SEL_RANGE, SEL_INDEX = 0, 1, 2

_DTYPE_CODE = {
    np.dtype(np.uint8): MES_UINT8,
    np.dtype(np.int8): MES_INT8,
    np.dtype(np.int32): MES_INT32,
    np.dtype(np.int64): MES_INT64,
    np.dtype(np.float32): MES_FLOAT32,
    np.dtype(np.float64): MES_FLOAT64,
}
_CODE_DTYPE = {v: k for k, v in _DTYPE_CODE.items()}


class MestraError(Exception):
    """The one error: `rule` is the spec's rule id ("E7") or empty, `path`
    a concept path or empty, `message` what went wrong and how to fix it."""

    def __init__(self, rule: str, message: str, path: str = "") -> None:
        super().__init__(f"{rule}: {message}" if rule else message)
        self.rule = rule
        self.message = message
        self.path = path


class _Error(ctypes.Structure):
    _fields_ = [("rule", ctypes.c_char * 8), ("path", ctypes.c_char * 512),
                ("message", ctypes.c_char * 2048)]


class _Sel(ctypes.Structure):
    _fields_ = [("kind", ctypes.c_int), ("start", ctypes.c_int64),
                ("stop", ctypes.c_int64), ("index", ctypes.POINTER(ctypes.c_int64)),
                ("count", ctypes.c_int64)]


def _library_name() -> str:
    if sys.platform == "darwin":
        return "libmestra.dylib"
    if sys.platform.startswith("win"):
        return "mestra.dll"
    return "libmestra.so"


def _find_library() -> str:
    explicit = os.environ.get("MESTRA_LIBRARY")
    if explicit:
        return explicit
    here = Path(__file__).resolve().parent
    for candidate in (here / "_native" / _library_name(),
                      here.parents[1] / "build" / _library_name()):
        if candidate.exists():
            return str(candidate)
    raise ImportError(
        f"the mestra core library ({_library_name()}) was not found; "
        "set MESTRA_LIBRARY to its path or build core/ first")


_lib = ctypes.CDLL(_find_library())

_P = ctypes.c_void_p
_S = ctypes.c_char_p
_I = ctypes.c_int
_L = ctypes.c_int64
_D = ctypes.c_double
_E = ctypes.POINTER(_Error)
_SEL = ctypes.POINTER(_Sel)
_PP = ctypes.POINTER(ctypes.c_void_p)
_SS = ctypes.POINTER(ctypes.c_char_p)

_SIGNATURES: dict[str, tuple[Any, list[Any]]] = {
    "mes_version": (_S, []),
    "mes_format": (_S, []),
    "mes_create": (_I, [_S, _S, _S, _S, _PP, _E]),
    "mes_open_append": (_I, [_S, _PP, _E]),
    "mes_set_attribute": (_I, [_P, _S, _S, _E]),
    "mes_declare_parameter": (_I, [_P, _S, _S, _S, _I, _I, _D, _D, _S, _E]),
    "mes_declare_label": (_I, [_P, _S, _S, _SS, _L, _E]),
    "mes_declare_result": (_I, [_P, _S, _S, _S, _I, _S, _S, _I, _D, _S, _S, _S, _S, _I, _S, _S, _E]),
    "mes_declare_mesh_label": (_I, [_P, _S, _S, _SS, _L, _E]),
    "mes_declare_coordinates": (_I, [_P, _S, _I, _I, _S, _S, _E]),
    "mes_create_model": (_I, [_S, _S, _S, _S, _PP, _E]),
    "mes_tree_new": (_I, [_PP, _E]),
    "mes_tree_free": (None, [_P]),
    "mes_tree_set_null": (_I, [_P, _S, _E]),
    "mes_tree_set_bool": (_I, [_P, _S, _I, _E]),
    "mes_tree_set_int": (_I, [_P, _S, _L, _E]),
    "mes_tree_set_float": (_I, [_P, _S, _D, _E]),
    "mes_tree_set_string": (_I, [_P, _S, _S, _E]),
    "mes_tree_set_array": (_I, [_P, _S, _I, _P, _I, ctypes.POINTER(_L), _E]),
    "mes_tree_set_strings": (_I, [_P, _S, _SS, _L, _E]),
    "mes_tree_set_dict": (_I, [_P, _S, _E]),
    "mes_tree_keys": (_I, [_P, _S, _PP, _E]),
    "mes_tree_kind": (_I, [_P, _S, ctypes.POINTER(_I), _E]),
    "mes_tree_scalar": (_I, [_P, _S, ctypes.POINTER(_L), ctypes.POINTER(_D), _E]),
    "mes_tree_strings": (_I, [_P, _S, _PP, _E]),
    "mes_tree_array_info": (_I, [_P, _S, ctypes.POINTER(_I), ctypes.POINTER(_I), ctypes.POINTER(_L), _E]),
    "mes_tree_array": (_I, [_P, _S, _P, _L, _E]),
    "mes_add_model": (_I, [_P, _S, _S, _SS, _L, _P, _S, _E]),
    "mes_model_numbers": (_I, [_P, _S, _PP, _E]),
    "mes_nearest_check": (_I, [_P, _E]),
    "mes_nearest_output_size": (_I, [_P, _S, ctypes.POINTER(_L), _E]),
    "mes_nearest_call": (_I, [_P, _SS, ctypes.POINTER(ctypes.POINTER(_D)), _I, _L, _S, ctypes.POINTER(_D), _L, _E]),
    "mes_evaluate_begin": (_I, [_P, _S, _PP, _E]),
    "mes_set_constant": (_I, [_P, _S, _S, _I, _D, _L, _E]),
    "mes_set_generalisation_group": (_I, [_P, _S, _E]),
    "mes_set_compression": (_I, [_P, _I, _I, _E]),
    "mes_geometry_begin": (_I, [_P, _E]),
    "mes_geometry_points": (_I, [_P, _I, _P, _L, _I, _E]),
    "mes_geometry_cells": (_I, [_P, _P, _L, _P, _P, _L, _E]),
    "mes_geometry_label": (_I, [_P, _S, _P, _L, _E]),
    "mes_set_mesh": (_I, [_P, _E]),
    "mes_batch_begin": (_I, [_P, _L, _E]),
    "mes_batch_values": (_I, [_P, _S, _I, _P, _L, _E]),
    "mes_batch_names": (_I, [_P, _S, _SS, _L, _E]),
    "mes_batch_geometry_for_row": (_I, [_P, _E]),
    "mes_batch_geometry_for_member": (_I, [_P, _S, _E]),
    "mes_batch_commit": (_I, [_P, ctypes.POINTER(_L), _E]),
    "mes_flush": (_I, [_P, _E]),
    "mes_close": (_I, [_P, _E]),
    "mes_open": (_I, [_S, _PP, _E]),
    "mes_set_threads": (_I, [_P, _I, _E]),
    "mes_info": (_I, [_P, _S, _PP, _E]),
    "mes_names": (_I, [_P, _S, _PP, _E]),
    "mes_describe": (_I, [_P, _S, _PP, _PP, _E]),
    "mes_shape": (_I, [_P, _S, _SEL, _SEL, ctypes.POINTER(_L), ctypes.POINTER(_I), _E]),
    "mes_read": (_I, [_P, _S, _SEL, _SEL, _I, _P, _L, _E]),
    "mes_label_names": (_I, [_P, _S, _SEL, _PP, _E]),
    "mes_table": (_I, [_P, _S, _PP, _E]),
    "mes_validate": (_I, [_S, _PP, _E]),
    "mes_report_count": (_L, [_P]),
    "mes_report_get": (_I, [_P, _L, _SS, _SS, _SS, _SS]),
    "mes_report_free": (None, [_P]),
    "mes_strings_count": (_L, [_P]),
    "mes_strings_get": (_S, [_P, _L]),
    "mes_strings_free": (None, [_P]),
}

for _name, (_res, _args) in _SIGNATURES.items():
    _fn = getattr(_lib, _name)
    _fn.restype = _res
    _fn.argtypes = _args


def b(text: str | None) -> bytes | None:
    """UTF-8 for the C side; None stays NULL."""
    return None if text is None else str(text).encode("utf-8")


def call(name: str, *args: Any) -> None:
    """Calls a mes_* function that returns a status, raising MestraError."""
    err = _Error()
    status = getattr(_lib, name)(*args, ctypes.byref(err))
    if status != 0:
        raise MestraError(err.rule.decode("utf-8", "replace"),
                          err.message.decode("utf-8", "replace"),
                          err.path.decode("utf-8", "replace"))


def strings_out(name: str, *args: Any) -> list[str]:
    """Calls a function whose last output is a mes_strings list."""
    handle = ctypes.c_void_p()
    call(name, *args, ctypes.byref(handle))
    try:
        n = _lib.mes_strings_count(handle)
        return [_lib.mes_strings_get(handle, i).decode("utf-8") for i in range(n)]
    finally:
        _lib.mes_strings_free(handle)


def two_strings_out(name: str, *args: Any) -> tuple[list[str], list[str]]:
    keys, values = ctypes.c_void_p(), ctypes.c_void_p()
    call(name, *args, ctypes.byref(keys), ctypes.byref(values))
    try:
        out = []
        for h in (keys, values):
            n = _lib.mes_strings_count(h)
            out.append([_lib.mes_strings_get(h, i).decode("utf-8") for i in range(n)])
        return out[0], out[1]
    finally:
        _lib.mes_strings_free(keys)
        _lib.mes_strings_free(values)


def string_array(items: Sequence[str]) -> Any:
    arr = (ctypes.c_char_p * max(len(items), 1))()
    for i, s in enumerate(items):
        arr[i] = str(s).encode("utf-8")
    return arr


def dtype_code(values: np.ndarray) -> int:
    try:
        return _DTYPE_CODE[values.dtype]
    except KeyError:
        raise MestraError("E4", f"values of dtype {values.dtype} cannot be stored; "
                                "use float32, float64, int32 or int64") from None


def as_array(values: Any) -> np.ndarray:
    """A C-contiguous numeric array; Python ints become int64, floats float64."""
    arr = np.asarray(values)
    if arr.dtype == np.bool_:
        raise MestraError("", "booleans are label values; declare the label with "
                              "categories ['false', 'true'] (or as bool)")
    if arr.dtype.kind == "i" and arr.dtype not in _DTYPE_CODE:
        arr = arr.astype(np.int64)
    if arr.dtype.kind == "u" and arr.dtype != np.uint8:
        arr = arr.astype(np.int64)
    if arr.dtype.kind == "f" and arr.dtype not in _DTYPE_CODE:
        arr = arr.astype(np.float64)
    return np.ascontiguousarray(arr)


class Selection:
    """A row, node or cell selection in the core's form."""

    def __init__(self, sel: Any, what: str) -> None:
        self.sel = _Sel()
        self.single = False
        self._keep: np.ndarray | None = None
        if sel is None:
            self.sel.kind = SEL_ALL
        elif isinstance(sel, slice):
            if sel.step not in (None, 1):
                raise MestraError("", f"{what}: a slice must have step 1")
            self.sel.kind = SEL_RANGE
            self._slice = sel
        elif isinstance(sel, (int, np.integer)):
            self.single = True
            self._keep = np.array([int(sel)], dtype=np.int64)
            self.sel.kind = SEL_INDEX
        else:
            self._keep = np.ascontiguousarray(np.asarray(sel, dtype=np.int64).ravel())
            self.sel.kind = SEL_INDEX
        self._slice = sel if isinstance(sel, slice) else None
        if self._keep is not None:
            self.sel.index = self._keep.ctypes.data_as(ctypes.POINTER(ctypes.c_int64))
            self.sel.count = len(self._keep)

    def resolve(self, length: int) -> None:
        """Turns a slice into a range now that the length is known."""
        if self._slice is not None:
            start, stop, _ = self._slice.indices(length)
            self.sel.start, self.sel.stop = start, max(start, stop)

    def pointer(self) -> Any:
        return ctypes.byref(self.sel)


def read(handle: Any, name: str, rows: Selection, sites: Selection, dtype: np.dtype) -> np.ndarray:
    shape = (ctypes.c_int64 * 4)()
    rank = ctypes.c_int()
    call("mes_shape", handle, b(name), rows.pointer(), sites.pointer(), shape, ctypes.byref(rank))
    dims = tuple(shape[i] for i in range(rank.value))
    out = np.empty(dims, dtype=dtype)
    call("mes_read", handle, b(name), rows.pointer(), sites.pointer(), _DTYPE_CODE[np.dtype(dtype)],
         out.ctypes.data_as(ctypes.c_void_p), out.nbytes)
    return out


def version() -> str:
    return _lib.mes_version().decode()


def format_string() -> str:
    return _lib.mes_format().decode()


def iterable(x: Any) -> bool:
    return isinstance(x, Iterable) and not isinstance(x, (str, bytes))

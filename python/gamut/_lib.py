"""The shared core, loaded with ctypes: the C interface of gamut.h and the
conversions every call needs.  Nothing here is public."""

from __future__ import annotations

import ctypes
import os
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

GAMUT_AS_GIVEN = 0
GAMUT_UINT8, GAMUT_INT8, GAMUT_INT32, GAMUT_INT64, GAMUT_FLOAT32, GAMUT_FLOAT64 = 1, 2, 3, 4, 5, 6
SEL_ALL, SEL_RANGE, SEL_INDEX = 0, 1, 2
# The most rows a selection scans (docs/security.md); the core refuses a
# larger file before it fills a buffer, so none larger is allocated.
MAX_ROWS_SCANNED = 1 << 27

_DTYPE_CODE = {
    np.dtype(np.uint8): GAMUT_UINT8,
    np.dtype(np.int8): GAMUT_INT8,
    np.dtype(np.int32): GAMUT_INT32,
    np.dtype(np.int64): GAMUT_INT64,
    np.dtype(np.float32): GAMUT_FLOAT32,
    np.dtype(np.float64): GAMUT_FLOAT64,
}


class GamutError(Exception):
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
        return "libgamut.dylib"
    if sys.platform.startswith("win"):
        return "gamut.dll"
    return "libgamut.so"


def _find_library() -> str:
    explicit = os.environ.get("GAMUT_LIBRARY")
    if explicit:
        return explicit
    here = Path(__file__).resolve().parent
    for candidate in (here / "_native" / _library_name(),
                      here.parents[1] / "build" / _library_name()):
        if candidate.exists():
            return str(candidate)
    raise ImportError(
        f"the Gamut core library ({_library_name()}) was not found; "
        "set GAMUT_LIBRARY to its path, or build it from a checkout: "
        "cmake -S . -B build && cmake --build build")


path = _find_library()
_lib = ctypes.CDLL(path)

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
    "gamut_version": (_S, []),
    "gamut_format": (_S, []),
    "gamut_units_valid": (_I, [_S]),
    "gamut_create": (_I, [_S, _S, _S, _S, _PP, _E]),
    "gamut_open_append": (_I, [_S, _PP, _E]),
    "gamut_set_attribute": (_I, [_P, _S, _S, _E]),
    "gamut_declare_parameter": (_I, [_P, _S, _S, _S, _I, _I, _D, _D, _S, _E]),
    "gamut_declare_label": (_I, [_P, _S, _S, _SS, _L, _E]),
    "gamut_declare_result": (_I, [_P, _S, _S, _S, _I, _S, _S, _I, _D, _S, _S, _S, _S, _I, _S, _S, _E]),
    "gamut_declare_mesh_label": (_I, [_P, _S, _S, _SS, _L, _E]),
    "gamut_declare_coordinates": (_I, [_P, _S, _I, _I, _S, _S, _E]),
    "gamut_create_model": (_I, [_S, _S, _S, _S, _PP, _E]),
    "gamut_tree_new": (_I, [_PP, _E]),
    "gamut_tree_free": (None, [_P]),
    "gamut_tree_set_null": (_I, [_P, _S, _E]),
    "gamut_tree_set_bool": (_I, [_P, _S, _I, _E]),
    "gamut_tree_set_int": (_I, [_P, _S, _L, _E]),
    "gamut_tree_set_float": (_I, [_P, _S, _D, _E]),
    "gamut_tree_set_string": (_I, [_P, _S, _S, _E]),
    "gamut_tree_set_array": (_I, [_P, _S, _I, _P, _L, _I, ctypes.POINTER(_L), _E]),
    "gamut_tree_set_strings": (_I, [_P, _S, _SS, _L, _E]),
    "gamut_tree_set_dict": (_I, [_P, _S, _E]),
    "gamut_tree_keys": (_I, [_P, _S, _PP, _E]),
    "gamut_tree_kind": (_I, [_P, _S, ctypes.POINTER(_I), _E]),
    "gamut_tree_scalar": (_I, [_P, _S, ctypes.POINTER(_L), ctypes.POINTER(_D), _E]),
    "gamut_tree_strings": (_I, [_P, _S, _PP, _E]),
    "gamut_tree_array_info": (_I, [_P, _S, ctypes.POINTER(_I), ctypes.POINTER(_I), ctypes.POINTER(_L), _I, _E]),
    "gamut_tree_array": (_I, [_P, _S, _P, _L, _E]),
    "gamut_add_model": (_I, [_P, _S, _S, _SS, _L, _P, _S, _E]),
    "gamut_model_numbers": (_I, [_P, _S, _PP, _E]),
    "gamut_nearest_check": (_I, [_P, _E]),
    "gamut_nearest_output_size": (_I, [_P, _S, ctypes.POINTER(_L), _E]),
    "gamut_nearest_call": (_I, [_P, _SS, ctypes.POINTER(ctypes.POINTER(_D)), ctypes.POINTER(_L), _I, _L, _S,
                               ctypes.POINTER(_D), _L, _E]),
    "gamut_evaluation_begin": (_I, [_P, _L, _S, _PP, _E]),
    "gamut_evaluation_values": (_I, [_P, _S, _I, _P, _L, _E]),
    "gamut_evaluation_names": (_I, [_P, _S, _SS, _L, _E]),
    "gamut_evaluation_coordinates": (_I, [_P, _I, _P, _L, _E]),
    "gamut_evaluation_ready": (_I, [_P, _PP, _PP, _E]),
    "gamut_evaluation_requests": (_I, [_P, _S, _PP, _PP, _PP, _E]),
    "gamut_evaluation_input_info": (_I, [_P, _S, ctypes.POINTER(_I), ctypes.POINTER(_I), ctypes.POINTER(_L), _I,
                                         _E]),
    "gamut_evaluation_input": (_I, [_P, _S, _P, _L, _E]),
    "gamut_evaluation_answer": (_I, [_P, _S, _S, _S, _S, ctypes.POINTER(_D), _L, _E]),
    "gamut_evaluation_finish": (_I, [_P, _E]),
    "gamut_evaluation_free": (None, [_P]),
    "gamut_set_constant": (_I, [_P, _S, _S, _I, _D, _L, _E]),
    "gamut_set_generalisation_group": (_I, [_P, _S, _E]),
    "gamut_set_compression": (_I, [_P, _I, _I, _E]),
    "gamut_geometry_begin": (_I, [_P, _E]),
    "gamut_geometry_points": (_I, [_P, _I, _P, _L, _L, _I, _E]),
    "gamut_geometry_cells": (_I, [_P, _P, _L, _P, _L, _P, _L, _E]),
    "gamut_geometry_label": (_I, [_P, _S, _P, _L, _E]),
    "gamut_set_mesh": (_I, [_P, _E]),
    "gamut_batch_begin": (_I, [_P, _L, _E]),
    "gamut_batch_values": (_I, [_P, _S, _I, _P, _L, _L, _E]),
    "gamut_batch_names": (_I, [_P, _S, _SS, _L, _E]),
    "gamut_batch_geometry_for_row": (_I, [_P, _E]),
    "gamut_batch_geometry_for_member": (_I, [_P, _S, _E]),
    "gamut_batch_commit": (_I, [_P, ctypes.POINTER(_L), _E]),
    "gamut_flush": (_I, [_P, _E]),
    "gamut_set_note_text": (_I, [_P, _S, _S, _E]),
    "gamut_set_note_int": (_I, [_P, _S, _L, _E]),
    "gamut_set_note_float": (_I, [_P, _S, _D, _E]),
    "gamut_set_private": (_I, [_P, _S, ctypes.c_char_p, _L, _E]),
    "gamut_notes": (_I, [_P, _PP, _PP, _PP, _E]),
    "gamut_private_names": (_I, [_P, _PP, _E]),
    "gamut_get_private": (_I, [_P, _S, _P, _L, ctypes.POINTER(_L), _E]),
    "gamut_close": (_I, [_P, _E]),
    "gamut_append": (_I, [_S, _S, ctypes.POINTER(_L), _E]),
    "gamut_extract": (_I, [_S, _S, _SEL, _E]),
    "gamut_write_copy": (_I, [_S, _S, _E]),
    "gamut_abandon": (None, [_P, _I]),
    "gamut_open": (_I, [_S, _PP, _E]),
    "gamut_set_threads": (_I, [_P, _I, _E]),
    "gamut_info": (_I, [_P, _S, _PP, _E]),
    "gamut_names": (_I, [_P, _S, _PP, _E]),
    "gamut_describe": (_I, [_P, _S, _PP, _PP, _E]),
    "gamut_related": (_I, [_P, _S, _PP, _PP, _PP, _E]),
    "gamut_shape": (_I, [_P, _S, _SEL, _SEL, ctypes.POINTER(_I), ctypes.POINTER(_L), _I, _E]),
    "gamut_read": (_I, [_P, _S, _SEL, _SEL, _I, _P, _L, _E]),
    "gamut_label_names": (_I, [_P, _S, _SEL, _PP, _E]),
    "gamut_outside": (_I, [_P, _S, _SEL, _P, _L, _E]),
    "gamut_table": (_I, [_P, _S, _PP, _E]),
    "gamut_select": (_I, [_P, _S, ctypes.POINTER(_L), _L, ctypes.POINTER(_L), _E]),
    "gamut_validate": (_I, [_S, _PP, _E]),
    "gamut_report_count": (_L, [_P]),
    "gamut_report_get": (_I, [_P, _L, _SS, _SS, _SS, _SS]),
    "gamut_report_free": (None, [_P]),
    "gamut_strings_count": (_L, [_P]),
    "gamut_strings_get": (_S, [_P, _L]),
    "gamut_strings_free": (None, [_P]),
}

for _name, (_res, _args) in _SIGNATURES.items():
    _fn = getattr(_lib, _name)
    _fn.restype = _res
    _fn.argtypes = _args


def b(text: str | None) -> bytes | None:
    """UTF-8 for the C side; None stays NULL.  A C string ends at its first
    NUL, so text holding one is refused rather than cut short."""
    if text is None:
        return None
    # surrogateescape keeps a file name that is not UTF-8 as the bytes it was
    # given; the core refuses such bytes in a name (E8) and opens such a path.
    raw = str(text).encode("utf-8", "surrogateescape")
    if b"\0" in raw:
        raise GamutError("", f"{text!r} holds a NUL character, which no name or text may hold")
    return raw


def call(name: str, *args: Any) -> None:
    """Calls a gamut_* function that returns a status, raising GamutError."""
    err = _Error()
    status = getattr(_lib, name)(*args, ctypes.byref(err))
    if status != 0:
        raise GamutError(err.rule.decode("utf-8", "replace"),
                          err.message.decode("utf-8", "replace"),
                          err.path.decode("utf-8", "replace"))


def strings_out(name: str, *args: Any) -> list[str]:
    """Calls a function whose last output is a gamut_strings list."""
    handle = ctypes.c_void_p()
    call(name, *args, ctypes.byref(handle))
    try:
        n = _lib.gamut_strings_count(handle)
        # Text the file stores as invalid UTF-8 (E3 to the validator) is shown, not raised.
        return [_lib.gamut_strings_get(handle, i).decode("utf-8", "replace") for i in range(n)]
    finally:
        _lib.gamut_strings_free(handle)


def lists_out(name: str, count: int, *args: Any) -> list[list[str]]:
    """Calls a function whose last `count` outputs are gamut_strings lists."""
    handles = [ctypes.c_void_p() for _ in range(count)]
    call(name, *args, *(ctypes.byref(h) for h in handles))
    try:
        return [[_lib.gamut_strings_get(h, i).decode("utf-8", "replace")
                 for i in range(_lib.gamut_strings_count(h))] for h in handles]
    finally:
        for h in handles:
            _lib.gamut_strings_free(h)


def two_strings_out(name: str, *args: Any) -> tuple[list[str], list[str]]:
    keys, values = lists_out(name, 2, *args)
    return keys, values


def string_array(items: Sequence[str]) -> Any:
    arr = (ctypes.c_char_p * max(len(items), 1))()
    for i, s in enumerate(items):
        arr[i] = b(s)
    return arr


def dtype_code(values: np.ndarray) -> int:
    try:
        return _DTYPE_CODE[values.dtype]
    except KeyError:
        raise GamutError("E4", f"values of dtype {values.dtype} cannot be stored; "
                                "use float32, float64, int32 or int64") from None


def int64_exactly(values: Any, what: str) -> np.ndarray:
    """Values as int64 when each is a whole number within its range, compared
    exactly; a cast would round a fraction or wrap a large unsigned value
    without a word."""
    arr = np.asarray(values)
    if arr.dtype.kind == "i" or (arr.dtype.kind == "u" and arr.dtype.itemsize < 8):
        return arr.astype(np.int64)
    if arr.dtype.kind == "u":                     # 64-bit unsigned, in either byte order
        if arr.size and arr.max() > np.iinfo(np.int64).max:
            raise GamutError("E4", f"{what}: {arr.max()} is above int64's range")
        return arr.astype(np.int64)
    if arr.dtype.kind == "b":
        raise GamutError("E4", f"{what} is int64 and takes numbers, not booleans")
    if arr.dtype.kind in "USVMm":
        raise GamutError("E4", f"{what} is int64 and takes numbers, not {arr.dtype}")
    if arr.dtype.kind == "f":                     # whole and in range, compared in its own dtype
        whole = np.all(np.isfinite(arr)) and np.all(arr == np.round(arr))
        if whole and float(np.finfo(arr.dtype).max) >= 2.0**63:   # a float16 cannot reach them
            lo, hi = arr.dtype.type(-2.0**63), arr.dtype.type(2.0**63)
            whole = bool(np.all((arr >= lo) & (arr < hi)))
        if arr.size and not whole:
            raise GamutError("E4", f"{what} is int64 and takes whole numbers in its range")
        return arr.astype(np.int64)
    out = np.empty(arr.shape, dtype=np.int64)
    flat = out.reshape(-1)
    for k, v in enumerate(arr.reshape(-1).tolist()):
        if isinstance(v, (str, bytes, bool)):     # Fraction would parse "1e3"
            raise GamutError("E4", f"{what} is int64 and takes numbers; {v!r} is not one")
        try:
            exact = Fraction(v)                   # ints, floats and Decimals exactly
        except (TypeError, ValueError, OverflowError):
            raise GamutError("E4", f"{what} is int64 and takes whole numbers; {v!r} is not one") from None
        if exact.denominator != 1 or not -2**63 <= exact.numerator < 2**63:
            raise GamutError("E4", f"{what} is int64 and takes whole numbers in its range; "
                                   f"{v!r} is not one")
        flat[k] = exact.numerator
    return out


def float64_exactly(values: Any, what: str) -> np.ndarray:
    """Values as float64, refusing an integer a float64 would round (past
    2**53), as the core does: for values computed with here before the core
    sees them. Values NumPy itself reads as floats (a float array, a list
    with a float in it) are floats already."""
    arr = np.asarray(values)
    if arr.dtype.kind in "iuO":
        flat = arr.reshape(-1)
        if arr.dtype.kind != "O":
            flat = flat[(flat > 2**53) | (flat < -2**53)]
        for v in flat.tolist():
            if isinstance(v, (int, np.integer)) and not isinstance(v, (bool, np.bool_)) \
                    and abs(int(v)) > 2**53:
                v = int(v)
                try:
                    exact = int(float(v)) == v
                except OverflowError:
                    exact = False
                if not exact:
                    raise GamutError("E4", f"{what}: {v} is not exact as a float64, which holds "
                                           "every integer only to 2^53")
    return np.asarray(arr, dtype=np.float64)


def int64_value(value: Any, what: str) -> int:
    """One integer as a Python int in int64's range: ctypes would wrap one
    outside it without a word."""
    v = int(value)
    if not -2**63 <= v < 2**63:
        raise GamutError("E4", f"{what}: {v} is outside int64's range")
    return v


def as_array(values: Any) -> np.ndarray:
    """A C-contiguous numeric array; Python ints become int64, floats float64."""
    arr = np.asarray(values)
    if arr.dtype == np.bool_:
        raise GamutError("", "booleans are label values; declare the label with "
                              "categories ['false', 'true'] (or as bool)")
    if arr.dtype.kind == "i" and arr.dtype not in _DTYPE_CODE:
        arr = arr.astype(np.int64)
    if arr.dtype.kind == "u" and arr.dtype != np.uint8:
        arr = int64_exactly(arr, "values")
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
                raise GamutError("", f"{what}: a slice must have step 1")
            self.sel.kind = SEL_RANGE
            self._slice = sel
        elif isinstance(sel, (int, np.integer)) and not isinstance(sel, (bool, np.bool_)):
            self.single = True
            self._keep = np.array([int(sel)], dtype=np.int64)
            self.sel.kind = SEL_INDEX
        else:
            given = np.asarray(sel)
            if given.size and given.dtype.kind not in "iu":
                raise GamutError("", f"{what}: positions are integers, a slice or None; "
                                      f"got {given.dtype} values")
            if given.dtype.kind == "u" and given.size and given.max() > np.iinfo(np.int64).max:
                raise GamutError("", f"{what}: position {given.max()}, counting from 0, "
                                      "is outside the positions")
            self._keep = np.ascontiguousarray(given.astype(np.int64).ravel())
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
    call("gamut_shape", handle, b(name), rows.pointer(), sites.pointer(), ctypes.byref(rank), shape, len(shape))
    dims = tuple(shape[i] for i in range(rank.value))
    out = np.empty(dims, dtype=dtype)
    call("gamut_read", handle, b(name), rows.pointer(), sites.pointer(), _DTYPE_CODE[np.dtype(dtype)],
         out.ctypes.data_as(ctypes.c_void_p), out.nbytes)
    return out


def outside(handle: Any, name: str, rows: Selection) -> np.ndarray:
    shape = (ctypes.c_int64 * 4)()
    rank = ctypes.c_int()
    call("gamut_shape", handle, b(name), rows.pointer(), None, ctypes.byref(rank), shape, len(shape))
    # Sized as a read of the parameter; for any other name the core refuses.
    out = np.empty(shape[0] if rank.value == 1 else 0, dtype=np.float64)
    call("gamut_outside", handle, b(name), rows.pointer(), out.ctypes.data_as(ctypes.c_void_p),
         out.nbytes)
    return out


def units_valid(units: str) -> bool:
    return bool(_lib.gamut_units_valid(b(units)))


def version() -> str:
    return _lib.gamut_version().decode()


def format_string() -> str:
    return _lib.gamut_format().decode()


def iterable(x: Any) -> bool:
    return isinstance(x, Iterable) and not isinstance(x, (str, bytes))

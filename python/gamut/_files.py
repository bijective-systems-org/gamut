"""Copies between files, done by the core: each validates its source and
checks everything before the first row is written."""

from __future__ import annotations

import ctypes
import os
from typing import Any

from . import _lib
from ._lib import Selection, b, call


def _path(p: Any) -> bytes:
    return b(os.fspath(p))


def append(dst: str, src: Any, marking: str | None = None) -> int:
    """Adds the rows of `src` to `dst` and returns how many. The rows get
    new ids continuing dst's; category tables merge by name. Both files
    need the same declarations (bounds may differ), the same mesh, and one
    geometry for a group member found in both. A marked `src` whose
    portion marking is not dst's is refused (E27); `marking` states the
    marking the result carries, which dst then carries, whatever the two
    files did.

    `src` may be a list (or tuple) of files: the result of appending them
    one by one, in order, made at once, so `dst` is copied once and gets
    every file's rows or none. An error names the file it is about."""
    n = ctypes.c_int64()
    if isinstance(src, (list, tuple)):
        paths = (ctypes.c_char_p * max(len(src), 1))(*[_path(p) for p in src])
        call("gamut_append_files", _path(dst), paths, len(src),
             None if marking is None else b(marking), ctypes.byref(n))
    elif marking is None:
        call("gamut_append", _path(dst), _path(src), ctypes.byref(n))
    else:
        call("gamut_append_marked", _path(dst), _path(src), b(marking), ctypes.byref(n))
    return n.value


def extract(src: str, dst: str, rows: Any) -> None:
    """Writes the selected rows of `src` (positions, a slice, or a strictly
    increasing array) as a new file `dst` (which must not exist): ids kept, every table whole, a
    changing mesh's instances reduced to those the rows use."""
    sel = Selection(rows, "rows")
    if isinstance(rows, slice):
        from ._study import open as _open
        with _open(os.fspath(src)) as f:
            sel.resolve(f.row_count)
    call("gamut_extract", _path(src), _path(dst), sel.pointer())


def write_copy(src: str, dst: str) -> None:
    """Rewrites `src` as `dst` with the default layout (chunks and
    compression), as for a file another writer chunked finely; the copy
    keeps the file's identity (file_id, created). The destination must not exist."""
    call("gamut_write_copy", _path(src), _path(dst))

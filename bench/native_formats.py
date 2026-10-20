"""Small benchmark bindings to the installed CGNS and Exodus C libraries.

Library paths are explicit: CGNS_LIBRARY and EXODUS_LIBRARY. CGNS_INDEX_BYTES
must match cgsize_t in that library's cgnstypes.h (4 or 8). No format is
implemented here: the native libraries write and read their own files.
"""

from __future__ import annotations

import ctypes as ct
import os
from contextlib import contextmanager

import numpy as np

I, L, P, S = ct.c_int, ct.c_int64, ct.c_void_p, ct.c_char_p
IP = ct.POINTER(I)
# VTK type: CGNS element enum, Exodus name, nodes/cell, topological dimension.
CELLS = {3: (3, b"BAR2", 2, 1), 5: (5, b"TRI3", 3, 2),
         9: (7, b"QUAD4", 4, 2), 10: (10, b"TETRA4", 4, 3),
         12: (17, b"HEX8", 8, 3)}


def pointer(a):
    return a.ctypes.data_as(P)


class Library:
    def __init__(self, name, prefix):
        self.path = os.environ[name]
        self.lib = ct.CDLL(self.path)
        self.prefix = "" if hasattr(self.lib, prefix) else "vtk" + (
            "cgns_" if name == "CGNS_LIBRARY" else "exodusII_")

    def bind(self, name, args, result=I):
        f = getattr(self.lib, self.prefix + name)
        f.argtypes, f.restype = args, result
        setattr(self, name, f)


class CGNS(Library):
    def __init__(self):
        super().__init__("CGNS_LIBRARY", "cg_open")
        self.index = {4: ct.c_int32, 8: ct.c_int64}[int(os.environ["CGNS_INDEX_BYTES"])]
        self.dtype = np.dtype("i" + str(ct.sizeof(self.index)))
        for name, args in {
            "cg_open": [S, I, IP], "cg_close": [I], "cg_get_error": [],
            "cg_set_file_type": [I], "cg_version": [I, ct.POINTER(ct.c_float)],
            "cg_base_write": [I, S, I, I, IP],
            "cg_zone_write": [I, I, S, P, I, IP], "cg_zone_read": [I, I, I, P, P],
            "cg_coord_write": [I, I, I, I, S, P, IP],
            "cg_coord_read": [I, I, I, S, I, P, P, P],
            "cg_section_write": [I, I, I, S, I, self.index, self.index, I, P, IP],
            "cg_section_read": [I, I, I, I, P, IP, P, P, IP, IP],
            "cg_elements_read": [I, I, I, I, P, P],
            "cg_sol_write": [I, I, I, S, I, IP],
            "cg_field_write": [I, I, I, I, I, S, P, IP],
            "cg_field_read": [I, I, I, I, S, I, P, P, P],
        }.items():
            self.bind(name, args, S if name == "cg_get_error" else I)

    def check(self, code):
        if code:
            raise RuntimeError(self.cg_get_error().decode())

    @contextmanager
    def opened(self, path, write=False):
        fn = I()
        if write:
            self.check(self.cg_set_file_type(2))  # HDF5 backend, native defaults
        self.check(self.cg_open(os.fsencode(path), 1 if write else 0, ct.byref(fn)))
        try:
            yield fn.value
        finally:
            self.check(self.cg_close(fn.value))

    def write(self, path, points, cells, fields):
        types, offsets, conn = cells
        kind, = np.unique(types)
        element, _, width, dimension = CELLS[int(kind)]
        indices = np.ascontiguousarray(conn + 1, dtype=self.dtype)
        size = np.array([len(points), len(types), 0], dtype=self.dtype)
        with self.opened(path, True) as f:
            b, z, k = I(), I(), I()
            self.check(self.cg_base_write(f, b"Study", dimension, points.shape[1], ct.byref(b)))
            self.check(self.cg_zone_write(f, 1, b"Mesh", pointer(size), 3, ct.byref(z)))
            for axis in range(points.shape[1]):
                values = np.ascontiguousarray(points[:, axis], dtype="f8")
                self.check(self.cg_coord_write(f, 1, 1, 4, b"Coordinate" + b"XYZ"[axis:axis+1],
                                               pointer(values), ct.byref(k)))
            self.check(self.cg_section_write(f, 1, 1, b"Cells", element, 1, len(types), 0,
                                             pointer(indices), ct.byref(k)))
            for step in range(len(next(iter(fields.values())))):
                self.check(self.cg_sol_write(f, 1, 1, f"Run{step}".encode(), 2, ct.byref(k)))
                for name, rows in fields.items():
                    values = np.ascontiguousarray(rows[step], dtype="f8")
                    self.check(self.cg_field_write(f, 1, 1, step + 1, 4, name.encode(),
                                                   pointer(values), ct.byref(k)))

    def field(self, f, name, steps, lo, hi):
        low, high = self.index(lo + 1), self.index(hi)
        values = np.empty((len(steps), hi - lo), dtype="f8")
        for row, step in enumerate(steps):
            self.check(self.cg_field_read(f, 1, 1, int(step) + 1, name.encode(), 4,
                                          ct.byref(low), ct.byref(high), pointer(values[row])))
        return values

    def mesh(self, f):
        size = np.zeros(9, dtype=self.dtype)
        name = ct.create_string_buffer(33)
        self.check(self.cg_zone_read(f, 1, 1, name, pointer(size)))
        # Coordinate count is recorded by the benchmark's common payload.
        n, count = int(size[0]), int(size[1])
        points = []
        low, high = self.index(1), self.index(n)
        for axis in b"XYZ":
            a = np.empty(n, dtype="f8")
            code = self.cg_coord_read(f, 1, 1, b"Coordinate" + bytes([axis]), 4,
                                      ct.byref(low), ct.byref(high), pointer(a))
            if code and axis == ord("Z"):
                break
            self.check(code)
            points.append(a)
        kind, start, end, boundary, parent = I(), self.index(), self.index(), I(), I()
        self.check(self.cg_section_read(f, 1, 1, 1, name, ct.byref(kind), ct.byref(start),
                                        ct.byref(end), ct.byref(boundary), ct.byref(parent)))
        vtk_type = next(t for t, spec in CELLS.items() if spec[0] == kind.value)
        width = CELLS[vtk_type][2]
        conn = np.empty(count * width, dtype=self.dtype)
        self.check(self.cg_elements_read(f, 1, 1, 1, pointer(conn), None))
        return np.stack(points, axis=1), (np.full(count, vtk_type, dtype="u1"),
                np.arange(count + 1, dtype="i8") * width, conn.astype("i8") - 1)


class Exodus(Library):
    def __init__(self, compressed=False):
        super().__init__("EXODUS_LIBRARY", "ex_open_int")
        self.api = int(os.environ["EXODUS_API_VERSION"])
        self.compressed = compressed
        for name, args in {
            "ex_create_int": [S, I, IP, IP, I],
            "ex_open_int": [S, I, IP, IP, ct.POINTER(ct.c_float), I], "ex_close": [I],
            "ex_put_init": [I, S, L, L, L, L, L, L],
            "ex_get_init": [I, P, IP, IP, IP, IP, IP, IP],
            "ex_put_coord": [I, P, P, P], "ex_get_coord": [I, P, P, P],
            "ex_put_block": [I, I, L, S, L, L, L, L, L],
            "ex_get_block": [I, I, L, P, IP, IP, IP, IP, IP],
            "ex_put_conn": [I, I, L, P, P, P], "ex_get_conn": [I, I, L, P, P, P],
            "ex_put_variable_param": [I, I, I],
            "ex_set_option": [I, I, I],
            "ex_put_variable_names": [I, I, I, ct.POINTER(S)],
            "ex_put_time": [I, I, P], "ex_put_var": [I, I, I, I, L, L, P],
            "ex_get_partial_var": [I, I, I, I, L, L, L, P],
            "ex_get_var_time": [I, I, I, L, I, I, P],
        }.items():
            self.bind(name, args)

    def check(self, code):
        if code < 0:
            raise RuntimeError(f"Exodus native call returned {code}")

    @contextmanager
    def opened(self, path, write=False):
        cpu, disk, version = I(8), I(8 if write else 0), ct.c_float()
        f = (self.ex_create_int(os.fsencode(path), 8 | 64, ct.byref(cpu), ct.byref(disk), self.api)
             if write else self.ex_open_int(os.fsencode(path), 2, ct.byref(cpu), ct.byref(disk),
                                            ct.byref(version), self.api))
        self.check(f)
        try:
            if write and self.compressed:
                self.check(self.ex_set_option(f, 3, 1))  # gzip level 1
                self.check(self.ex_set_option(f, 4, 1))  # shuffle
            yield f
        finally:
            self.check(self.ex_close(f))

    def write(self, path, points, cells, fields):
        types, offsets, conn = cells
        kind, = np.unique(types)
        _, element, width, _ = CELLS[int(kind)]
        indices = np.ascontiguousarray(conn + 1, dtype="i4")
        with self.opened(path, True) as f:
            self.check(self.ex_put_init(f, b"Parametric study: run index is the time coordinate",
                                       points.shape[1], len(points), len(types), 1, 0, 0))
            axes = [np.ascontiguousarray(points[:, i], dtype="f8") for i in range(points.shape[1])]
            self.check(self.ex_put_coord(f, *([pointer(a) for a in axes] + [None] * (3-len(axes)))))
            self.check(self.ex_put_block(f, 1, 1, element, len(types), width, 0, 0, 0))
            self.check(self.ex_put_conn(f, 1, 1, pointer(indices), None, None))
            self.check(self.ex_put_variable_param(f, 14, len(fields)))
            names = (S * len(fields))(*(n.encode() for n in fields))
            self.check(self.ex_put_variable_names(f, 14, len(fields), names))
            for step in range(len(next(iter(fields.values())))):
                time = ct.c_double(step)
                self.check(self.ex_put_time(f, step + 1, ct.byref(time)))
                for k, rows in enumerate(fields.values()):
                    values = np.ascontiguousarray(rows[step], dtype="f8")
                    self.check(self.ex_put_var(f, step + 1, 14, k + 1, 1, len(points), pointer(values)))

    def field(self, f, index, steps, lo, hi):
        values = np.empty((len(steps), hi - lo), dtype="f8")
        if hi - lo == 1 and len(steps) > 1 and np.all(np.diff(steps) == 1):
            self.check(self.ex_get_var_time(f, 14, index + 1, lo + 1,
                                            int(steps[0]) + 1, int(steps[-1]) + 1, pointer(values)))
        else:
            for row, step in enumerate(steps):
                self.check(self.ex_get_partial_var(f, int(step) + 1, 14, index + 1, 1,
                                                   lo + 1, hi - lo, pointer(values[row])))
        return values

    def mesh(self, f):
        title = ct.create_string_buffer(81)
        dims, n, count, blocks, nodesets, sidesets = (I() for _ in range(6))
        self.check(self.ex_get_init(f, title, *(ct.byref(v) for v in
                   (dims, n, count, blocks, nodesets, sidesets))))
        axes = [np.empty(n.value, dtype="f8") for _ in range(dims.value)]
        self.check(self.ex_get_coord(f, *([pointer(a) for a in axes] + [None] * (3-len(axes)))))
        name = ct.create_string_buffer(33)
        number, width, edges, faces, attrs = (I() for _ in range(5))
        self.check(self.ex_get_block(f, 1, 1, name, *(ct.byref(v) for v in
                   (number, width, edges, faces, attrs))))
        vtk_type = next(t for t, spec in CELLS.items() if spec[1] == name.value)
        conn = np.empty(count.value * width.value, dtype="i4")
        self.check(self.ex_get_conn(f, 1, 1, pointer(conn), None, None))
        return np.stack(axes, axis=1), (np.full(count.value, vtk_type, dtype="u1"),
                np.arange(count.value + 1, dtype="i8") * width.value, conn.astype("i8") - 1)

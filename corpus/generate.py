"""The cross-language corpus: files written from the specification with h5py
alone (no Gamut code), and what every binding must find in them.

    python corpus/generate.py OUTDIR

writes OUTDIR/<case>.gamut and OUTDIR/expected.json.  `check.py` holds a
binding to it.  Three groups of cases:

  valid/   each file type and feature; expected: no finding, and probe
           values a reader must return exactly;
  rules/   a valid file broken to break one rule; expected: that rule
           among the findings;
  hostile/ files that must be refused cleanly (no crash, no hang).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys

import h5py
import numpy as np

T = 262_144
NULL = b"\x00null"


# --- writing the layout of spec section 10 by hand -------------------------------


def utf8(text: str) -> np.ndarray:
    raw = text.encode("utf-8")
    return np.array(raw if raw else b"\x00", dtype=h5py.string_dtype("utf-8", max(len(raw), 1)))


def sattr(obj, name: str, text: str) -> None:
    if name in obj.attrs:
        del obj.attrs[name]
    obj.attrs.create(name, utf8(text))


def fattr(obj, name: str, value: float) -> None:
    obj.attrs.create(name, np.float64(value))


def iattr(obj, name: str, value: int) -> None:
    obj.attrs.create(name, np.int64(value))


def scale_name(n: int) -> str:
    return "This is a netCDF dimension but not a netCDF variable.%10d" % n


def dim(f, path: str, n: int, unlimited: bool) -> None:
    d = f.create_dataset(path, shape=(n,), maxshape=(None if unlimited else n,),
                         dtype=">f4", chunks=(1 if unlimited else max(n, 1),), track_order=True)
    d.make_scale(scale_name(n))


def leading_chunk(item: int, trailing: tuple) -> tuple:
    b = item * int(np.prod([t or 1 for t in trailing], dtype=np.int64))
    if b <= T:
        return (min(512, max(1, T // b)),) + tuple(t or 1 for t in trailing)
    rest = item * int(np.prod([t or 1 for t in trailing[1:]], dtype=np.int64))
    return (1, min(trailing[0], max(1, T // rest))) + tuple(t or 1 for t in trailing[1:])


def end_chunk(item: int, trailing: tuple, n: int | None = None) -> tuple:
    b = item * int(np.prod([t or 1 for t in trailing], dtype=np.int64))
    c = max(1, T // b)
    if n is not None:
        c = min(c, max(n, 1))
    return (c,) + tuple(t or 1 for t in trailing)


class Study:
    """One file being written by hand."""

    def __init__(self, path: str, kind: str = "data") -> None:
        self.f = h5py.File(path, "w", libver=("earliest", "v110"), track_order=False)
        f = self.f
        sattr(f, "format", "gamut/1")
        sattr(f, "kind", kind)
        sattr(f, "writer", "corpus generator")
        sattr(f, "created", "2026-10-18T00:00:00Z")
        sattr(f, "file_id", "00000000-0000-4000-8000-000000000000")
        self.rows = 0
        self.root_names: list[str] = []
        self.params_and_labels: list[str] = []

    def row(self, n: int) -> None:
        self.rows = n
        d = self.f.create_dataset("row", data=np.arange(n, dtype="<i8"), maxshape=(None,),
                                  chunks=leading_chunk(8, ()), compression="gzip",
                                  compression_opts=1, shuffle=True, track_order=True)
        d.make_scale("row")

    def column(self, name: str, data, dtype: str, attrs: dict) -> h5py.Dataset:
        data = np.asarray(data, dtype=dtype)
        d = self.f.create_dataset(name, data=data, maxshape=(None,),
                                  chunks=leading_chunk(data.dtype.itemsize, ()),
                                  compression="gzip", compression_opts=1, shuffle=True)
        d.dims[0].attach_scale(self.f["row"])
        for k, v in attrs.items():
            (sattr if isinstance(v, str) else fattr)(d, k, v)
        return d

    def table(self, name: str, entries: list[str]) -> None:
        width = max([len(e.encode()) for e in entries] + [1])
        dim(self.f, f"category_{name}", len(entries), True)
        d = self.f.create_dataset(f"categories/{name}", shape=(len(entries),), maxshape=(None,),
                                  dtype=h5py.string_dtype("utf-8", width),
                                  chunks=leading_chunk(width, ()), compression="gzip",
                                  compression_opts=1, shuffle=True)
        if entries:
            d[:] = np.array([e.encode() for e in entries], dtype=h5py.string_dtype("utf-8", width))
        d.dims[0].attach_scale(self.f[f"category_{name}"])

    def parameter(self, name, values, role, units, lower=None, upper=None, run_group=None,
                  dtype="<f8"):
        attrs = {"role": role, "units": units}
        if lower is not None:
            attrs["lower"], attrs["upper"] = float(lower), float(upper)
        if run_group:
            attrs["run_group"] = run_group
        self.column(name, values, dtype, attrs)
        self.params_and_labels.append(name)

    def label(self, name, codes, role, categories):
        self.table(name, categories)
        self.column(name, codes, "<i4", {"role": role, "category": name})
        self.params_and_labels.append(name)

    def scalar(self, name, values, units, dtype="<f8", **rel):
        attrs = {"role": "scalar", "units": units}
        attrs.update(rel)
        return self.column(name, values, dtype, attrs)

    def constant(self, name, value, units):
        d = self.f.create_dataset(name, data=np.float64(value))
        sattr(d, "role", "constant")
        sattr(d, "units", units)

    def finish(self) -> None:
        names = " ".join(sorted(self.params_and_labels, key=lambda s: s.encode()))
        for name, obj in self.f.items():
            if isinstance(obj, h5py.Dataset) and obj.attrs.get("role") == b"scalar" and names:
                sattr(obj, "coordinates", names)
        self.f.close()

    # --- a shared mesh ------------------------------------------------------------

    def shared_mesh(self, per: str, n_nodes: int, axes: int, cells=None):
        f = self.f
        m = f.create_group("mesh")
        sattr(m, "kind", "shared")
        sattr(m, "per", per)
        dim(f, "mesh/node", n_nodes, False)
        dim(f, "mesh/axis", axes, False)
        types = offsets = conn = np.zeros(0)
        if cells is not None:
            types, offsets, conn = (np.asarray(cells[0], "u1"), np.asarray(cells[1], "<i8"),
                                    np.asarray(cells[2], "<i8"))
            dim(f, "mesh/cell", len(types), False)
            dim(f, "mesh/cell_plus_one", len(offsets), False)
            dim(f, "mesh/index", len(conn), False)
            for name, data, scale in (("cell_types", types, "cell"),
                                      ("cell_offsets", offsets, "cell_plus_one"),
                                      ("cell_connectivity", conn, "index")):
                d = f.create_dataset(f"mesh/{name}", data=data,
                                     chunks=end_chunk(data.dtype.itemsize, (), len(data)),
                                     compression="gzip", compression_opts=1, shuffle=True)
                d.dims[0].attach_scale(f[f"mesh/{scale}"])
        self.n_nodes, self.n_cells, self.axes = n_nodes, len(types), axes
        return types, offsets, conn

    def support_id(self, types, offsets, conn, cloud=None) -> None:
        h = hashlib.sha256()
        h.update(np.int64(self.n_nodes).tobytes())
        h.update(np.asarray(types, "u1").tobytes())
        h.update(np.asarray(offsets, "<i8").tobytes())
        h.update(np.asarray(conn, "<i8").tobytes())
        if cloud is not None:
            h.update(np.asarray(cloud, "<f8").tobytes())
        sattr(self.f["mesh"], "support_id", h.hexdigest())

    def coordinates(self, data, units, leading: str | None) -> None:
        f = self.f
        data = np.asarray(data, "<f8")
        if leading is None:
            d = f.create_dataset("mesh/coordinates", data=data, chunks=end_chunk(8, data.shape[1:], data.shape[0]),
                                 compression="gzip", compression_opts=1, shuffle=True)
            d.dims[0].attach_scale(f["mesh/node"])
            d.dims[1].attach_scale(f["mesh/axis"])
        else:
            d = f.create_dataset("mesh/coordinates", data=data, maxshape=(None,) + data.shape[1:],
                                 chunks=leading_chunk(8, data.shape[1:]), compression="gzip",
                                 compression_opts=1, shuffle=True)
            d.dims[0].attach_scale(f[leading])
            d.dims[1].attach_scale(f["mesh/node"])
            d.dims[2].attach_scale(f["mesh/axis"])
        sattr(d, "units", units)

    def mesh_label(self, name, where, values, category=None):
        f = self.f
        values = np.asarray(values, "<i4")
        d = f.create_dataset(f"mesh/{where}_labels/{name}", data=values,
                             chunks=end_chunk(4, (), len(values)), compression="gzip",
                             compression_opts=1, shuffle=True)
        d.dims[0].attach_scale(f[f"mesh/{where}"])
        if category:
            sattr(d, "category", category)

    def field(self, name, where, values, units, dtype="<f8", **attrs):
        f = self.f
        values = np.asarray(values, dtype)
        d = f.create_dataset(f"mesh/{where}_fields/{name}", data=values,
                             maxshape=(None, values.shape[1]),
                             chunks=leading_chunk(values.dtype.itemsize, values.shape[1:]),
                             compression="gzip", compression_opts=1, shuffle=True)
        d.dims[0].attach_scale(f["row"])
        d.dims[1].attach_scale(f[f"mesh/{where}"])
        sattr(d, "units", units)
        for k, v in attrs.items():
            (sattr if isinstance(v, str) else (iattr if isinstance(v, int) else fattr))(d, k, v)
        return d


def quad_grid(nx, ny, scale=1.0):
    xs, ys = np.meshgrid(np.arange(nx) * scale, np.arange(ny) * scale)
    pts = np.stack([xs.ravel(), ys.ravel()], axis=1)
    conn = []
    for j in range(ny - 1):
        for i in range(nx - 1):
            a = j * nx + i
            conn += [a, a + 1, a + nx + 1, a + nx]
    n = (nx - 1) * (ny - 1)
    return pts, (np.full(n, 9), np.arange(0, 4 * n + 1, 4), np.array(conn))


# --- valid cases --------------------------------------------------------------------


def case_table(path):
    s = Study(path)
    s.row(4)
    s.parameter("mach", [0.3, 0.4, 0.5, 0.6], "condition", "1", 0.0, 1.0)
    s.parameter("t", [0.0, 1.0, 0.0, 1.0], "time", "s", run_group="run")
    s.label("run", [0, 0, 1, 1], "group", ["a", "b"])
    s.label("status", [0, 0, 0, 0], "status", ["converged", "failed"])
    s.scalar("cl", [0.1, 0.2, 0.3, 0.4], "1")
    s.scalar("cd", np.array([0.01, 0.02, 0.03, 0.04], "<f4"), "1", dtype="<f4")
    s.scalar("cl_std", [0.01] * 4, "1", of="cl", statistic="std")
    s.scalar("cl_hi", [0.2, 0.3, 0.4, 0.5], "1", of="cl", statistic="quantile", q=0.975)
    s.scalar("dcl_dmach", [0.5] * 4, "1", of="cl", with_respect_to="mach")
    s.constant("s_ref", 12.5, "m2")
    sattr(s.f, "generalisation_group", "run")
    s.finish()
    return {"probes": [
        {"read": "cl", "rows": [1, 3], "dtype": "float64", "values": [0.2, 0.4]},
        {"read": "cd", "rows": None, "dtype": "float32",
         "values": np.array([0.01, 0.02, 0.03, 0.04], "<f4").astype(float).tolist()},
        {"label": "run", "rows": None, "names": ["a", "a", "b", "b"]},
        {"select": "mach > 0.35 and run == b", "positions": [2, 3]},
        {"select": "(mach>0.35)and(run==b)", "positions": [2, 3]},
        {"info": "addons", "value": ["time", "gradients", "uncertainty"]},
        {"info": "type", "value": "table"},
    ]}


def case_shared_fixed(path):
    pts, cells = quad_grid(3, 3)
    s = Study(path)
    s.row(2)
    s.parameter("k", [1.0, 2.0], "design", "1")
    t, o, c = s.shared_mesh("fixed", 9, 2, cells)
    s.coordinates(pts, "m", None)
    s.support_id(t, o, c)
    s.table("zone", ["in", "out"])
    s.mesh_label("zone", "cell", [0, 0, 1, 1], "zone")
    p = np.arange(18.0).reshape(2, 9)
    s.field("p", "node", p, "Pa")
    s.field("u", "cell", np.ones((2, 4)), "m s-1", vector="vel", axis="x")
    s.field("v", "cell", np.zeros((2, 4)), "m s-1", vector="vel", axis="y")
    s.field("p_r", "node", p, "Pa", _QuantizeBitRoundNumberOfSignificantBits=10)
    s.finish()
    return {"probes": [
        {"read": "p", "rows": [1], "sites": [2, 3, 4], "dtype": "float64", "values": [[11.0, 12.0, 13.0]]},
        {"read": "p", "rows": None, "sites": [0], "dtype": "float64", "values": [[0.0], [9.0]]},
        {"read": "coordinates", "rows": None, "dtype": "float64", "values": pts.tolist()},
        {"read": "zone", "rows": None, "dtype": "int64", "values": [0, 0, 1, 1]},
        {"read": "cells/connectivity", "rows": None, "dtype": "int64", "values": cells[2].tolist()},
        {"info": "type", "value": "shared"},
    ]}


def case_point_cloud(path):
    taps = np.array([[0.0], [0.1], [0.25], [0.5]])
    s = Study(path)
    s.row(2)
    s.parameter("alpha", [0.0, 4.0], "condition", "degree")
    s.shared_mesh("fixed", 4, 1, None)
    s.coordinates(taps, "m", None)
    s.support_id([], [], [], cloud=taps)
    s.field("cp", "node", [[0.1, 0.2, 0.3, 0.4], [0.5, 0.6, 0.7, 0.8]], "1")
    s.finish()
    return {"probes": [{"read": "cp", "rows": [1], "sites": None, "dtype": "float64",
                        "values": [[0.5, 0.6, 0.7, 0.8]]}]}


def case_shared_group(path):
    """Members arriving out of their declared order, numbered by appearance."""
    pts, cells = quad_grid(2, 2)
    s = Study(path)
    s.row(4)
    s.label("member", [2, 2, 0, 1], "group", ["a", "b", "c"])   # c first, then a, then b
    s.parameter("mach", [5.0, 8.0, 5.0, 8.0], "condition", "1")
    t, o, c = s.shared_mesh("group:member", 4, 2, cells)
    dim(s.f, "mesh/instance", 3, True)
    geoms = np.stack([pts * 3, pts * 1, pts * 2])        # instance 0 = c, 1 = a, 2 = b
    s.coordinates(geoms, "m", "mesh/instance")
    s.support_id(t, o, c)
    s.column("mesh/row_instance", [0, 0, 1, 2], "<i8", {})
    s.field("p", "node", np.ones((4, 4)), "Pa")
    s.finish()
    return {"probes": [
        {"read": "coordinates", "rows": [1], "dtype": "float64", "values": [(pts * 3).tolist()]},
        {"read": "coordinates", "rows": [3], "dtype": "float64", "values": [(pts * 2).tolist()]},
    ]}


def case_changing(path):
    big, bc = quad_grid(3, 3)
    small, sc = quad_grid(2, 2)
    s = Study(path)
    s.row(3)
    s.parameter("r", [1.0, 2.0, 3.0], "design", "m")
    f = s.f
    m = f.create_group("mesh")
    sattr(m, "kind", "changing")
    sattr(m, "per", "run")
    nodes = [9, 4, 9]
    cells_n = [4, 1, 4]
    insts = [(big, bc), (small, sc), (big, bc)]
    total_n, total_c = sum(nodes), sum(cells_n)
    conn = np.concatenate([c[2] for _, c in insts])
    types = np.concatenate([c[0] for _, c in insts]).astype("u1")
    offs = [0]
    for _, c in insts:
        offs += (np.asarray(c[1][1:]) + offs[-1]).tolist()
    for name, n in (("instance_plus_one", 4), ("node", total_n), ("cell", total_c),
                    ("cell_plus_one", total_c + 1), ("index", len(conn)),
                    ("node_value", total_n), ("cell_value", total_c)):
        dim(f, f"mesh/{name}", n, True)
    dim(f, "mesh/axis", 2, False)

    def e2e(name, data, scale, dtype, trailing=()):
        data = np.asarray(data, dtype)
        d = f.create_dataset(f"mesh/{name}", data=data, maxshape=(None,) + data.shape[1:],
                             chunks=end_chunk(data.dtype.itemsize, data.shape[1:]),
                             compression="gzip", compression_opts=1, shuffle=True)
        d.dims[0].attach_scale(f[f"mesh/{scale}"])
        if data.ndim == 2:
            d.dims[1].attach_scale(f["mesh/axis"])
        return d

    e2e("instance_nodes", np.cumsum([0] + nodes), "instance_plus_one", "<i8")
    e2e("instance_cells", np.cumsum([0] + cells_n), "instance_plus_one", "<i8")
    sattr(e2e("coordinates", np.concatenate([p for p, _ in insts]), "node", "<f8"), "units", "m")
    e2e("cell_types", types, "cell", "u1")
    e2e("cell_offsets", offs, "cell_plus_one", "<i8")
    e2e("cell_connectivity", conn, "index", "<i8")
    s.column("mesh/row_node_start", np.cumsum([0] + nodes[:-1]), "<i8", {})
    s.column("mesh/row_cell_start", np.cumsum([0] + cells_n[:-1]), "<i8", {})
    p = np.concatenate([np.arange(9.0), np.arange(4.0) + 100, np.arange(9.0) + 200])
    sattr(e2e("node_fields/p", p, "node_value", "<f8"), "units", "Pa")
    s.finish()
    return {"probes": [
        {"read": "p", "rows": [1], "sites": None, "dtype": "float64", "values": [100.0, 101.0, 102.0, 103.0]},
        {"read": "cells/connectivity", "rows": [1], "dtype": "int64", "values": [0, 1, 3, 2]},
        {"read": "cells/offsets", "rows": [2], "dtype": "int64", "values": [0, 4, 8, 12, 16]},
        {"info": "type", "value": "changing"},
    ]}


def case_model_nearest(path):
    s = Study(path, kind="model")
    s.row(0)
    s.parameter("mach", [], "condition", "1", 0.3, 0.6)
    s.parameter("alpha", [], "condition", "degree", 0.0, 4.0)
    d = s.scalar("cl", [], "1")
    sattr(d, "model", "fit")
    sattr(d, "output", "cl")
    g = s.f.create_group("models/fit")
    sattr(g, "type", "nearest")
    sattr(g, "inputs", "alpha mach")
    cols = g.create_dataset("columns", data=np.array([b"mach", b"alpha"], dtype=h5py.string_dtype("utf-8", 5)))
    lo = g.create_dataset("lower", data=np.array([0.3, 0.0]))
    hi = g.create_dataset("upper", data=np.array([0.6, 4.0]))
    x = g.create_dataset("x", data=np.array([[0.3, 0.0], [0.6, 4.0], [0.3, 4.0]]))
    out = g.create_group("outputs")
    y = out.create_dataset("cl", data=np.array([0.0, 0.5, 0.4]))
    for parent, name, ds in ((g, "columns", cols), (g, "lower", lo), (g, "upper", hi), (out, "cl", y)):
        dim(s.f, f"{parent.name}/gamut_{name}_d0", ds.shape[0], False)
        ds.dims[0].attach_scale(s.f[f"{parent.name}/gamut_{name}_d0"])
    dim(s.f, "models/fit/gamut_x_d0", 3, False)
    dim(s.f, "models/fit/gamut_x_d1", 2, False)
    x.dims[0].attach_scale(s.f["models/fit/gamut_x_d0"])
    x.dims[1].attach_scale(s.f["models/fit/gamut_x_d1"])
    g.attrs.create("note", np.array(NULL, dtype=h5py.string_dtype("utf-8", 5)))
    s.finish()
    return {"probes": [
        {"evaluate": {"mach": [0.31, 0.58], "alpha": [3.9, 0.1]}, "scalar": "cl", "values": [0.4, 0.0]},
        {"info": "kind", "value": "model"},
    ]}


VALID = {"table": case_table, "shared_fixed": case_shared_fixed, "point_cloud": case_point_cloud,
         "shared_group": case_shared_group, "changing": case_changing,
         "model_nearest": case_model_nearest}


# --- rule cases: a valid file broken to break one rule ---------------------------------


def _replace(obj, name, maker):
    if name in obj.attrs:
        del obj.attrs[name]
    maker(obj)


RULES = {
    # name: (base case, rule, edit)
    "E1_format": ("table", "E1", lambda f: sattr(f, "format", "mestra/0")),
    "E1_kind": ("table", "E1", lambda f: sattr(f, "kind", "both")),
    "E2_file_id": ("table", "E2", lambda f: f.attrs.__delitem__("file_id")),
    "E3_lower_int": ("table", "E3", lambda f: _replace(f["mach"], "lower", lambda o: iattr(o, "lower", 0))),
    "E3_ascii_units": ("table", "E3", lambda f: _replace(f["cl"], "units", lambda o: o.attrs.create("units", np.bytes_(b"1")))),
    "E4_param_int32": ("table", "E4", lambda f: _swap(f, "mach", "<i4")),
    "E5_short_column": ("table", "E5", lambda f: f["cl"].resize((3,))),
    "E6_mesh_kind": ("shared_fixed", "E6", lambda f: sattr(f["mesh"], "kind", "wobbly")),
    "E6_cell_type": ("shared_fixed", "E6", lambda f: f["mesh/cell_types"].__setitem__(0, 42)),
    "E7_units": ("table", "E7", lambda f: sattr(f["cl"], "units", "m//s")),
    "E7_no_units": ("table", "E7", lambda f: f["mach"].attrs.__delitem__("units")),
    "E8_reserved": ("table", "E8", lambda f: f.move("cd", "category_cd")),
    "E9_code": ("table", "E9", lambda f: f["run"].__setitem__(0, 7)),
    "E9_repeat": ("table", "E9", lambda f: f["categories/run"].__setitem__(1, b"a")),
    "E10_node": ("shared_fixed", "E10", lambda f: f["mesh/cell_connectivity"].__setitem__(0, 99)),
    "E11_support": ("shared_fixed", "E11", lambda f: sattr(f["mesh"], "support_id", "0" * 64)),
    "E12_of": ("table", "E12", lambda f: sattr(f["cl_std"], "of", "nothing")),
    "E12_q": ("table", "E12", lambda f: fattr(f["cl_hi"], "q", 1.5)),
    "E12_units": ("table", "E12", lambda f: sattr(f["cl_std"], "units", "m")),
    "E13_axis": ("shared_fixed", "E13", lambda f: sattr(f["mesh/cell_fields/v"], "axis", "x")),
    "E14_ids": ("table", "E14", lambda f: f["row"].__setitem__(1, 0)),
    "E15_run_group": ("table", "E15", lambda f: sattr(f["t"], "run_group", "status")),
    "E16_bounds": ("table", "E16", lambda f: fattr(f["mach"], "lower", 2.0)),
    "E16_model_attr": ("table", "E16", lambda f: sattr(f["cl"], "model", "m")),
    "E16_coordinate_model": ("shared_fixed", "E16", lambda f: sattr(f["mesh/coordinates"], "model", "m")),
    "E17_input": ("model_nearest", "E17", lambda f: sattr(f["models/fit"], "inputs", "alpha mach beta")),
    "E17_nearest_bounds": ("model_nearest", "E17", lambda f: f["models/fit/upper"].__setitem__(0, 9.0)),
    "E18_codec": ("model_nearest", "E18", lambda f: f["models/fit"].create_dataset("bad", data=np.zeros(2, "<f4"))),
    "E19_scale": ("table", "E19", lambda f: f["cl"].dims[0].detach_scale(f["row"])),
    "E19_extent": ("shared_group", "E19", lambda f: f["mesh/instance"].resize((5,))),
    "E20_filter": ("table", "E20", lambda f: _swap(f, "cl", "<f8", compression="lzf")),
    "E21_instance": ("shared_group", "E21", lambda f: f["mesh/row_instance"].__setitem__(1, 1)),
    "E21_start": ("changing", "E21", lambda f: f["mesh/row_node_start"].__setitem__(1, 5)),
    "E22_soft": ("table", "E22", lambda f: f.__setitem__("alias", h5py.SoftLink("/cl"))),
    "E22_external": ("table", "E22", lambda f: f.__setitem__("ext", h5py.ExternalLink("x.h5", "/y"))),
    "W1_split": ("table", "W1", lambda f: _add_split(f, [0, 1, 0, 0])),
    "W2_status": ("table", "W2", lambda f: f["status"].__setitem__(2, 1)),
    "W3_nan": ("table", "W3", lambda f: f["cl"].__setitem__(0, np.nan)),
    "W4_bounds": ("table", "W4", lambda f: f["mach"].__setitem__(0, 5.0)),
    "W5_attr": ("table", "W5", lambda f: sattr(f["cl"], "colour", "blue")),
    "W5_role": ("table", "W5", lambda f: sattr(f["cd"], "role", "future")),
    "W5_statistic": ("table", "W5", lambda f: sattr(f["cl_std"], "statistic", "skewness")),
    "W6_chunk": ("table", "W6", lambda f: _swap(f, "cl", "<f8", chunks=(4096,))),
    "W7_wide": ("table", "W7", lambda f: _widen_table(f, "run")),
    "W8_created": ("table", "W8", lambda f: sattr(f, "created", "yesterday")),
    "W9_time": ("table", "W9", lambda f: f["t"].__setitem__(1, 0.0)),
    "W10_std": ("table", "W10", lambda f: f["cl_std"].__setitem__(0, -1.0)),
}


def _swap(f, name, dtype, compression="gzip", chunks=None):
    data = f[name][:]
    attrs = {k: f[name].attrs[k] for k in f[name].attrs if k not in ("DIMENSION_LIST",)}
    f[name].dims[0].detach_scale(f["row"])
    del f[name]
    kw = {"compression": compression}
    if compression == "gzip":
        kw.update(compression_opts=1, shuffle=True)
    d = f.create_dataset(name, data=data.astype(dtype), maxshape=(None,),
                         chunks=chunks or leading_chunk(np.dtype(dtype).itemsize, ()), **kw)
    for k, v in attrs.items():
        d.attrs.create(k, v)
    d.dims[0].attach_scale(f["row"])


def _add_split(f, codes):
    width = 5
    dim(f, "category_split", 2, True)
    t = f.create_dataset("categories/split", shape=(2,), maxshape=(None,),
                         dtype=h5py.string_dtype("utf-8", width), chunks=(512,),
                         compression="gzip", compression_opts=1, shuffle=True)
    t[:] = np.array([b"train", b"test"], dtype=h5py.string_dtype("utf-8", width))
    t.dims[0].attach_scale(f["category_split"])
    d = f.create_dataset("split", data=np.asarray(codes, "<i4"), maxshape=(None,), chunks=(512,),
                         compression="gzip", compression_opts=1, shuffle=True)
    d.dims[0].attach_scale(f["row"])
    sattr(d, "role", "split")
    sattr(d, "category", "split")


def _widen_table(f, name):
    entries = [e.rstrip(b"\x00") for e in f[f"categories/{name}"][:]]
    f[f"categories/{name}"].dims[0].detach_scale(f[f"category_{name}"])
    del f[f"categories/{name}"]
    t = f.create_dataset(f"categories/{name}", shape=(len(entries),), maxshape=(None,),
                         dtype=h5py.string_dtype("utf-8", 40), chunks=(512,), compression="gzip",
                         compression_opts=1, shuffle=True)
    t[:] = np.array(entries, dtype=h5py.string_dtype("utf-8", 40))
    t.dims[0].attach_scale(f[f"category_{name}"])


# --- hostile cases ----------------------------------------------------------------------


def hostile_cases(out):
    cases = {}
    p = os.path.join(out, "hostile_not_hdf5.gamut")
    open(p, "wb").write(b"\x89HDF not really" * 10)
    cases["hostile_not_hdf5"] = {"rules": ["E1"]}
    p = os.path.join(out, "hostile_deep.gamut")
    shutil.copy(os.path.join(out, "table.gamut"), p)
    with h5py.File(p, "r+") as f:
        g = f.create_group("notes")
        path = "notes"
        for i in range(80):
            path += f"/g{i}"
            f.create_group(path)
    cases["hostile_deep"] = {"rules": ["E23"]}
    p = os.path.join(out, "hostile_big_attr.gamut")
    shutil.copy(os.path.join(out, "table.gamut"), p)
    with h5py.File(p, "r+") as f:
        # A dataset with a version 2 object header can hold an attribute this
        # large; the attribute is one the spec names, as a huge array.
        d = f.create_dataset("cl_big", data=np.zeros(4), maxshape=(None,), chunks=(512,),
                             compression="gzip", compression_opts=1, shuffle=True,
                             track_order=True)
        d.dims[0].attach_scale(f["row"])
        sattr(d, "role", "scalar")
        sattr(d, "units", "1")
        d.attrs.create("of", np.zeros(2_000_000, dtype="S1"))
    cases["hostile_big_attr"] = {"rules": ["E3"]}
    p = os.path.join(out, "hostile_huge_dataset.gamut")
    shutil.copy(os.path.join(out, "table.gamut"), p)
    with h5py.File(p, "r+") as f:
        f.create_dataset("notes_huge", shape=(1 << 40,), dtype="<f8", chunks=(1 << 16,))
    cases["hostile_huge_dataset"] = {"rules": []}   # must not allocate; finding optional
    # A category table that declares 2**28 entries and stores none: read at
    # open, so it must be refused before its buffer is allocated.
    p = os.path.join(out, "hostile_table_huge.gamut")
    shutil.copy(os.path.join(out, "table.gamut"), p)
    with h5py.File(p, "r+") as f:
        n = 1 << 28
        dim(f, "category_huge", n, True)
        t = f.create_dataset("categories/huge", shape=(n,), maxshape=(None,),
                             dtype=h5py.string_dtype("utf-8", 24), chunks=(512,),
                             compression="gzip", compression_opts=1, shuffle=True)
        t.dims[0].attach_scale(f["category_huge"])
    cases["hostile_table_huge"] = {"rules": ["E23"]}
    # 2**33 rows declared, none stored: reading a label's names must not
    # allocate for them.
    p = os.path.join(out, "hostile_rows_huge.gamut")
    shutil.copy(os.path.join(out, "table.gamut"), p)
    with h5py.File(p, "r+") as f:
        for name in ("row", "run"):
            f[name].resize((1 << 33,))
    cases["hostile_rows_huge"] = {"rules": [], "reads": [{"label": "run"}]}
    # /row as a soft link to the real ids: links are never followed, and a
    # reader refuses rather than read the file as having no rows.
    p = os.path.join(out, "hostile_soft_row.gamut")
    shutil.copy(os.path.join(out, "table.gamut"), p)
    with h5py.File(p, "r+") as f:
        f.move("row", "row_real")
        f["row"] = h5py.SoftLink("/row_real")
    cases["hostile_soft_row"] = {"rules": ["E22"], "refused": "E22"}
    # A model whose arrays declare (2**62, 4) elements, none stored: the
    # element count overflows 64 bits once multiplied by the item size.
    p = os.path.join(out, "hostile_model_wrap.gamut")
    shutil.copy(os.path.join(out, "model_nearest.gamut"), p)
    with h5py.File(p, "r+") as f:
        g = f["models/fit"]
        for path in ("x", "outputs/cl"):
            del g[path]
            g.create_dataset(path, shape=(1 << 62, 4), maxshape=(None, 4), chunks=(1, 4),
                             dtype="<f8")
    cases["hostile_model_wrap"] = {"rules": ["E23"],
                                   "reads": [{"evaluate": {"mach": [0.4], "alpha": [1.0]}}]}
    # A changing mesh whose first instance claims 2**30 cells while
    # cell_offsets holds a handful.
    p = os.path.join(out, "hostile_cells_huge.gamut")
    shutil.copy(os.path.join(out, "changing.gamut"), p)
    with h5py.File(p, "r+") as f:
        f["mesh/instance_cells"][1] = 1 << 30
    cases["hostile_cells_huge"] = {"rules": ["E21"], "reads": [{"cells": 0}]}
    # 2**30 rows declared, one stored: the where selector reads every row.
    p = os.path.join(out, "hostile_where_huge.gamut")
    shutil.copy(os.path.join(out, "table.gamut"), p)
    with h5py.File(p, "r+") as f:
        for name in ("row", "mach"):
            f[name].resize((1 << 30,))
    cases["hostile_where_huge"] = {"rules": [], "reads": [{"select": "mach > 0.5"}]}
    # A scalar column of 2**21 one-element chunks, none written: HDF5 keeps
    # state per chunk touched, so reading it whole would take gigabytes.
    p = os.path.join(out, "hostile_tiny_chunks.gamut")
    shutil.copy(os.path.join(out, "table.gamut"), p)
    with h5py.File(p, "r+") as f:
        n = 1 << 21
        f["row"].resize((n,))
        attrs = {k: f["cl"].attrs[k] for k in f["cl"].attrs if k != "DIMENSION_LIST"}
        f["cl"].dims[0].detach_scale(f["row"])
        del f["cl"]
        d = f.create_dataset("cl", shape=(n,), maxshape=(None,), chunks=(1,), dtype="<f8")
        for k, v in attrs.items():
            d.attrs.create(k, v)
        d.dims[0].attach_scale(f["row"])
    cases["hostile_tiny_chunks"] = {"rules": [], "reads": [{"scalar": "cl"}]}
    # A point cloud whose fixed coordinates claim 2**40 nodes, none written:
    # the support id hashes them, so a checker must refuse before reading.
    p = os.path.join(out, "hostile_points_huge.gamut")
    shutil.copy(os.path.join(out, "point_cloud.gamut"), p)
    with h5py.File(p, "r+") as f:
        old = f["mesh/coordinates"]
        attrs = {k: old.attrs[k] for k in old.attrs if k != "DIMENSION_LIST"}
        axes = old.shape[1]
        old.dims[0].detach_scale(f["mesh/node"])
        old.dims[1].detach_scale(f["mesh/axis"])
        del f["mesh/coordinates"]
        d = f.create_dataset("mesh/coordinates", shape=(1 << 40, axes), chunks=(1 << 14, axes),
                             dtype="<f8")
        for k, v in attrs.items():
            d.attrs.create(k, v)
        d.dims[0].attach_scale(f["mesh/node"])
        d.dims[1].attach_scale(f["mesh/axis"])
    cases["hostile_points_huge"] = {"rules": ["E23"], "reads": []}
    # A nearest model without its upper bounds: evaluating checks the stored
    # numbers before it looks one up, and refuses (E17).
    p = os.path.join(out, "hostile_nearest_missing.gamut")
    shutil.copy(os.path.join(out, "model_nearest.gamut"), p)
    with h5py.File(p, "r+") as f:
        g = f["models/fit"]
        g["upper"].dims[0].detach_scale(g["gamut_upper_d0"])
        del g["upper"], g["gamut_upper_d0"]
    cases["hostile_nearest_missing"] = {"rules": ["E17"],
                                        "reads": [{"evaluate": {"mach": [0.4], "alpha": [1.0]}}]}
    # A model that does not say what it reads: evaluating refuses the
    # declaration it lacks rather than look it up.
    p = os.path.join(out, "hostile_model_undeclared.gamut")
    shutil.copy(os.path.join(out, "model_nearest.gamut"), p)
    with h5py.File(p, "r+") as f:
        del f["models/fit"].attrs["inputs"]
    cases["hostile_model_undeclared"] = {"rules": ["E17"],
                                         "reads": [{"evaluate": {"mach": [0.4], "alpha": [1.0]}}]}
    return cases


def main() -> None:
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    expected: dict[str, dict] = {}
    for name, make in VALID.items():
        e = make(os.path.join(out, f"{name}.gamut"))
        e["rules"] = []
        e["group"] = "valid"
        expected[name] = e
    for name, (base, rule, edit) in RULES.items():
        p = os.path.join(out, f"{name}.gamut")
        shutil.copy(os.path.join(out, f"{base}.gamut"), p)
        with h5py.File(p, "r+") as f:
            edit(f)
        expected[name] = {"group": "rules", "rules": [rule]}
    for name, e in hostile_cases(out).items():
        e["group"] = "hostile"
        expected[name] = e
    with open(os.path.join(out, "expected.json"), "w") as fh:
        json.dump(expected, fh, indent=1, sort_keys=True)
    print(f"{len(expected)} cases in {out}")


if __name__ == "__main__":
    main()

"""The version 1 test files, built from arrays, and how to compare two
files by content.

This module is also the one place the tests import the package by its
name: every version 1 test takes `lib` from here, so renaming the
package changes one line.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import h5py
import numpy as np

import mestra as lib  # the one import of the package by name

#: The package directory these tests must be running against.
PACKAGE_DIR = Path(__file__).resolve().parents[1] / "mestra"

CREATED = "2026-10-16T00:00:00Z"
WRITER = "mestra tests 1"

#: A quad mesh of six nodes and two cells (the worked example of the
#: version 0 support id).
QUAD_TYPES = np.array([9, 9], dtype=np.uint8)
QUAD_OFFSETS = np.array([0, 4, 8], dtype=np.int64)
QUAD_CONNECTIVITY = np.array([0, 1, 4, 3, 1, 2, 5, 4], dtype=np.int64)
QUAD_XY = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0],
                    [0.0, 1.0, 0.0], [1.0, 1.0, 0.0], [2.0, 1.0, 0.0]])


def assert_this_package() -> None:
    """The tests of generic tools must run against this checkout."""
    assert Path(lib.__file__).resolve().parent == PACKAGE_DIR, (
        lib.__file__, PACKAGE_DIR)


def table_dataset() -> Any:
    """A `table`: parameters, labels, per-row scalars and constants."""
    ds = lib.Dataset(writer=WRITER, created=CREATED)
    ds.title = "Wing table"
    ds.license = "CC-BY-4.0"
    ds.references = "doi:10.0000/example"
    ds.source = "panel code 3.1"
    ds.add_parameter("span", [10.0, 12.0, 14.0, 16.0], "design", "m",
                     lower=8.0, upper=18.0)
    ds.add_parameter("n_ribs", [4, 5, 6, 7], "design", "1", lower=4,
                     upper=7)
    ds.add_parameter("alpha", [0.0, 2.0, 4.0, 6.0], "condition",
                     "degree", lower=0.0, upper=8.0)
    ds.add_label("fidelity", [0, 1, 0, 1], "categorical",
                 categories=["panel", "rans"])
    ds.add_label("status", [0, 0, 0, 0], "status",
                 categories=["converged", "failed"])
    ds.add_label("case", [101, 102, 103, 104], "id")
    ds.add_scalar("cl", [0.1, 0.3, 0.5, 0.7], "1")
    ds.add_scalar("cd", [0.01, 0.012, 0.016, 0.022], "1", dtype="float32")
    ds.add_constant("s_ref", 12.5, "m2")
    ds.add_constant("l_ref", 1.25, "m")
    ds.notes["comment"] = "four runs"
    ds.notes["seed"] = 7
    ds.notes["weights"] = np.array([0.5, 1.5])
    return ds


def family_dataset() -> Any:
    """A `mesh` family: coordinates per member, pressure per row, a
    node and a cell label sharing a name, and a per-row cell label."""
    ds = lib.Dataset(writer=WRITER, created=CREATED)
    members = [0, 0, 1, 1, 2, 2]
    ds.add_parameter("mach", [0.5, 0.8, 0.5, 0.8, 0.5, 0.8], "condition",
                     "1", lower=0.5, upper=0.8)
    ds.add_label("member", members, "group",
                 categories=["m_a", "m_b", "m_c"])
    ds.set_generalisation_group("member")
    ds.add_label("status", [0, 0, 0, 1, 0, 0], "status",
                 categories=["converged", "failed"])
    ds.add_label("run", ["a-1", "a-2", "b-1", "b-2", "c-1", "c-2"], "id")
    ds.add_label("split", [0, 0, 0, 0, 1, 1], "split",
                 categories=["train", "test"])
    ds.add_scalar("cl", [0.2, 0.3, 0.25, 0.35, 0.22, 0.31], "1")
    coordinates = np.stack([QUAD_XY * (1.0 + 0.1 * m) for m in range(3)])
    mesh = ds.set_mesh((QUAD_TYPES, QUAD_OFFSETS, QUAD_CONNECTIVITY),
                       coordinates=coordinates, units="m",
                       dims=("group:member", "node", "component"))
    mesh.add_node_array("face", [1, 1, 2, 1, 1, 2], None, ("node",),
                        role="label")
    mesh.add_cell_array("face", [1, 2], None, ("cell",), role="label")
    ds.add_category_table("flag", ["ok", "separated"])
    mesh.add_cell_array("flagged", np.array([[0, 0], [0, 1], [0, 0],
                                             [1, 1], [0, 0], [0, 1]]),
                        None, ("row", "cell"), role="label",
                        category="flag")
    pressure = np.arange(36, dtype=np.float64).reshape(6, 6) * 10.0
    mesh.add_node_array("pressure", pressure, "Pa", ("row", "node"))
    velocity = np.arange(36, dtype=np.float64).reshape(6, 2, 3)
    mesh.add_cell_array("velocity", velocity, "m s-1",
                        ("row", "cell", "component"))
    return ds


def points_dataset() -> Any:
    """A `points` signal: each row a pressure signature sampled at the
    same times."""
    ds = lib.Dataset(writer=WRITER, created=CREATED)
    ds.add_parameter("mach", [1.4, 1.6, 1.8], "condition", "1",
                     lower=1.4, upper=1.8)
    ds.add_parameter("altitude", [12000.0, 15000.0, 18000.0],
                     "condition", "m", lower=12000.0, upper=18000.0)
    times = np.linspace(0.0, 0.2, 8)
    mesh = ds.set_mesh(coordinates=times, units="s", dims=("node",))
    signal = np.sin(np.outer([1.0, 2.0, 3.0], times * 30.0))
    mesh.add_node_array("dp", signal, "Pa", ("row", "node"))
    mesh.add_node_array("dp_std", np.full((3, 8), 0.1), "Pa",
                        ("row", "node"), statistic="std", of="dp")
    return ds


def model_affine() -> Any:
    """The affine model of the version 0 worked example, with a band on
    both outputs."""
    return lib.Affine(
        ["mach", "alpha"],
        {"cl": {"A": [[2.0, 0.1]], "b": [0.05], "shape": [],
                "uncertainty": [0.02], "level": 0.95,
                "method": "constant band"},
         "pressure": {"A": [[1.0, 0.0], [2.0, 0.0], [3.0, 0.5],
                            [4.0, 0.5], [5.0, 1.0], [6.0, 1.0]],
                      "b": [0.0, 0.1, 0.2, 0.3, 0.4, 0.5],
                      "shape": [6, 1],
                      "uncertainty": [0.05, 0.10, 0.15, 0.20, 0.25, 0.30],
                      "level": 0.68, "method": "constant band"}})


def model_dataset() -> Any:
    """A zero-row model: bounded parameters, a fixed mesh, and served
    scalar, field and band slots."""
    ds = lib.Dataset(writer=WRITER, created=CREATED)
    ds.add_parameter("mach", [], "condition", "1", lower=0.3, upper=0.9)
    ds.add_parameter("alpha", [], "condition", "degree", lower=0.0,
                     upper=8.0)
    mesh = ds.set_mesh((QUAD_TYPES, QUAD_OFFSETS, QUAD_CONNECTIVITY),
                       coordinates=QUAD_XY, units="m",
                       dims=("node", "component"))
    ds.add_callable("m1", model_affine(), inputs=["mach", "alpha"])
    ds.add_scalar("cl", None, "1", callable="m1", output="cl")
    ds.add_scalar("cl_band", None, "1", statistic="band", of="cl",
                  callable="m1", output="cl")
    mesh.add_node_array("pressure", None, "Pa", ("row", "node"),
                        callable="m1", output="pressure")
    mesh.add_node_array("pressure_band", None, "Pa", ("row", "node"),
                        statistic="band", of="pressure", callable="m1",
                        output="pressure")
    return ds


CASES = {
    "table": table_dataset,
    "family": family_dataset,
    "points": points_dataset,
    "model": model_dataset,
}


def write_case(name: str, directory: Any) -> str:
    path = os.path.join(str(directory), name + ".mes")
    lib.write(CASES[name](), path)
    return path


# ------------------------------------------------- content comparison

_IGNORED = frozenset(["CLASS", "NAME", "DIMENSION_LIST", "REFERENCE_LIST",
                      "_Netcdf4Dimid", "_Netcdf4Coordinates",
                      "_NCProperties"])


def content(path: str, layout: bool = False) -> dict[str, Any]:
    """Every object of a file with its attributes, dtype, shape,
    values and attached dimensions; with `layout`, also its chunks and
    filters. Two files with equal content say the same thing."""
    out: dict[str, Any] = {}
    with h5py.File(path, "r") as f:
        def visit(name: str, obj: Any) -> None:
            attrs = {}
            for key in obj.attrs:
                if key in _IGNORED:
                    continue
                value = obj.attrs[key]
                attrs[key] = value.tolist() if isinstance(
                    value, np.ndarray) else value
            entry: dict[str, Any] = {"attrs": attrs}
            if isinstance(obj, h5py.Dataset):
                entry["dtype"] = str(obj.dtype)
                entry["shape"] = obj.shape
                is_scale = obj.attrs.get("CLASS") == b"DIMENSION_SCALE"
                if not is_scale:
                    values = obj[()]
                    if isinstance(values, np.ndarray) and \
                            values.dtype.kind == "f":
                        values = values.view(
                            "u%d" % values.dtype.itemsize)
                    entry["values"] = values.tolist() if isinstance(
                        values, np.ndarray) else values
                    entry["dims"] = [[s.name for s in dim.values()]
                                     for dim in obj.dims]
                if layout:
                    entry["chunks"] = obj.chunks
                    entry["filters"] = (obj.compression,
                                        obj.compression_opts, obj.shuffle)
            out[name] = entry
        f.visititems(visit)
        out["/"] = {"attrs": {k: f.attrs[k] for k in f.attrs
                              if k not in _IGNORED}}
    return out

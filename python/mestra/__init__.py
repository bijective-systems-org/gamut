"""mestra: one file for a parametric simulation study, or a model
fitted to one, that says what every number is.

    import mestra

    with mestra.read("study.mes") as ds:
        print(ds.kind, ds.addons, ds.row_count)
        mach = ds.parameters["mach"].values()
        pressure = ds.mesh.node_arrays["pressure"].read(rows=slice(0, 4))
        print(pressure.dims)                    # row, node, component

    report = mestra.validate("study.mes")
    for finding in report.findings:
        print(finding)

The names in `__all__` are the whole public surface; everything else,
and every module or attribute whose name begins with `_`, is private.
This package reads and writes format version 1 (`mestra/1`);
`upgrade` converts a version 0 file.
"""

from __future__ import annotations

from .append import append
from .callables import (
    Affine,
    Callable,
    OpaqueCallable,
    Prediction,
    callable_types,
    input_table,
    register_callable,
)
from .errors import Finding, MestraError
from .evaluate import evaluate, prediction
from .model import FORMAT, Dataset, Label, Mesh, NamedArray, Parameter, Slot
from .reader import read
from .upgrade import upgrade
from .validator import Report, validate
from .writer import write

__version__ = "1.0.0.dev0"

__all__ = [
    "Affine",
    "Callable",
    "Dataset",
    "FORMAT",
    "Finding",
    "Label",
    "Mesh",
    "MestraError",
    "NamedArray",
    "OpaqueCallable",
    "Parameter",
    "Prediction",
    "Report",
    "Slot",
    "__version__",
    "append",
    "callable_types",
    "evaluate",
    "input_table",
    "prediction",
    "read",
    "register_callable",
    "upgrade",
    "validate",
    "write",
]

"""The public surface of the Python package, as data.

`generate()` lists every name in `mestra.__all__` with its kind and
signature, and for a class its public members: methods with their
signatures, properties, and the attributes an instance carries. A
member is public when its name does not begin with `_`. Signatures
carry parameter names, kinds and defaults, not annotations, so the
file changes when the interface does and not when a type hint does.
A class the library makes for the caller (a slot, a mesh, a report)
lists its members but not its constructor, which is not for callers.
Types that public calls return without being exported themselves
(the input table, a category table, the callables mapping) are pinned
under `returned`, by their members.

`python -m tests.surface` (from python/) writes docs/surface/python.json;
`tests/test_v1_surface.py` regenerates it and compares.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

import numpy as np

SURFACE = Path(__file__).resolve().parents[2] / "docs" / "surface" / \
    "python.json"

#: Classes the library makes and hands to the caller.
MADE_BY_LIBRARY = ("Finding", "Label", "Mesh", "OpaqueCallable",
                   "Parameter", "Report", "Slot")


def _signature(obj: Any) -> str:
    try:
        sig = inspect.signature(obj)
    except (TypeError, ValueError):
        return "(...)"
    plain = [p.replace(annotation=inspect.Parameter.empty)
             for p in sig.parameters.values()]
    return str(sig.replace(parameters=plain,
                           return_annotation=inspect.Signature.empty))


def _samples(lib: Any) -> dict[str, Any]:
    """One instance of each public class, to find what an instance
    carries."""
    ds = lib.Dataset(writer="surface", created="2026-10-16T00:00:00Z")
    parameter = ds.add_parameter("x", [1.0], "design", "1")
    label = ds.add_label("member", [0], "group", categories=["a"])
    slot = ds.add_scalar("y", [1.0], "1")
    mesh = ds.set_mesh(coordinates=[0.0], units="m", dims=("node",))
    return {
        "Dataset": ds, "Parameter": parameter, "Label": label,
        "Slot": slot, "Mesh": mesh,
        "NamedArray": lib.NamedArray([1.0], ("row",)),
        "Prediction": lib.Prediction(np.zeros(1)),
        "Report": lib.Report(),
        "Finding": lib.Finding("E01", "", "x"),
        "MestraError": lib.MestraError("", "x", ""),
        "OpaqueCallable": lib.OpaqueCallable("t", {}),
        "Affine": lib.Affine([], {}),
    }


def _ours(cls: type, name: str) -> bool:
    """True when `name` is defined by a class of this package, not by
    a builtin base such as Exception or object."""
    for base in cls.__mro__:
        if name in vars(base):
            return base.__module__.startswith("mestra")
    return False


def _members(cls: type, sample: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    for name in sorted(set(dir(cls))):
        if name.startswith("_") or not _ours(cls, name):
            continue
        raw = inspect.getattr_static(cls, name)
        if isinstance(raw, property):
            out[name] = "property"
        elif isinstance(raw, classmethod):
            out[name] = "classmethod " + _signature(getattr(cls, name))
        elif isinstance(raw, staticmethod):
            out[name] = "staticmethod " + _signature(getattr(cls, name))
        elif inspect.isfunction(raw):
            out[name] = "method " + _signature(raw)
        else:
            out[name] = "attribute"
    if sample is not None:
        for name in sorted(vars(sample) if hasattr(sample, "__dict__")
                           else ()):
            if not name.startswith("_") and name not in out:
                out[name] = "attribute"
        for name in getattr(type(sample), "__dataclass_fields__", {}):
            out.setdefault(name, "attribute")
    return out


def _returned(lib: Any, samples: dict[str, Any]) -> dict[str, Any]:
    """The members of types public calls return: `input_table(...)`,
    `Label.table` and `Dataset.categories`, `Dataset.callables`."""
    ds = samples["Dataset"]
    found = {
        "InputTable": lib.input_table(ds),
        "CategoryTable": ds.categories["member"],
        "Callables": ds.callables,
    }
    return {name: {"kind": "class",
                   "members": _members(type(value), value)}
            for name, value in sorted(found.items())}


def generate() -> dict[str, Any]:
    import mestra as lib

    samples = _samples(lib)
    names: dict[str, Any] = {}
    for name in sorted(lib.__all__):
        obj = getattr(lib, name)
        if inspect.isclass(obj):
            entry: dict[str, Any] = {
                "kind": "exception" if issubclass(obj, BaseException)
                else "class"}
            if name not in MADE_BY_LIBRARY:
                entry["signature"] = _signature(obj)
            entry["members"] = _members(obj, samples.get(name))
        elif callable(obj):
            entry = {"kind": "function", "signature": _signature(obj)}
        elif name == "__version__":
            entry = {"kind": "constant"}
        else:
            entry = {"kind": "constant", "value": obj}
        names[name] = entry
    return {"package": "mestra", "names": names,
            "returned": _returned(lib, samples)}


def text() -> str:
    return json.dumps(generate(), indent=2, sort_keys=True,
                      ensure_ascii=False) + "\n"


if __name__ == "__main__":
    SURFACE.parent.mkdir(parents=True, exist_ok=True)
    SURFACE.write_text(text(), encoding="utf-8")
    print("wrote %s" % SURFACE)

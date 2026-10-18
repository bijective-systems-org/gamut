"""Unit conversion (spec section 3.7), through pint when it is installed.

The file's units follow the UDUNITS grammar ("m s-1", "W m-2"); pint reads
a different spelling, so each string is translated first: a name's trailing
integer is its power ("s-1" is s**-1), and spaces or "." between powers
multiply.  Without pint, asking for a conversion says how to get it.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

import numpy as np

from ._lib import GamutError, units_parse

_TOKEN = re.compile(r"(\s+|\*\*|\*|/|\^|\(|\)|(?<![0-9])\.(?![0-9]))")
_POWER = re.compile(r"^([A-Za-z_%'\"][A-Za-z0-9_%'\"]*?[A-Za-z_%'\"]|[A-Za-z_%'\"])(-?[0-9]+)$")


def translate(units: str) -> str:
    """The pint spelling of a UDUNITS string."""
    if not units_parse(units):
        raise GamutError("E7", f"the units \"{units}\" do not parse (spec section 13)")
    if units.strip() == "1":
        return "dimensionless"
    parts = [p for p in _TOKEN.split(units.strip()) if p != ""]
    out: list[str] = []
    for p in parts:
        if p.isspace() or p == ".":
            out.append("*")
        elif p == "^":
            out.append("**")
        else:
            m = _POWER.match(p)
            out.append(f"{m.group(1)}**{m.group(2)}" if m else p)
    text = "".join(out)
    return re.sub(r"\*{3,}", "**", text)


@lru_cache(maxsize=1)
def _registry() -> Any:
    try:
        import pint
    except ImportError:
        raise GamutError("", "unit conversion needs pint: pip install pint "
                              "(or gamut-format[units])") from None
    return pint.UnitRegistry()


def convert(values: Any, from_units: str, to_units: str) -> np.ndarray:
    """`values` in `from_units`, converted to `to_units`."""
    if from_units == to_units:
        return np.asarray(values)
    ureg = _registry()
    try:
        q = ureg.Quantity(np.asarray(values, dtype=np.float64), translate(from_units))
        return np.asarray(q.to(translate(to_units)).magnitude)
    except GamutError:
        raise
    except Exception as e:   # pint's own errors: dimensionality, unknown names
        raise GamutError("", f"cannot convert {from_units} to {to_units}: {e}") from None

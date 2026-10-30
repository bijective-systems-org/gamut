"""Validation (spec section 16) through the core."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass, field

from . import _lib
from ._lib import b, call


@dataclass(frozen=True)
class Finding:
    """One finding: `rule` ("E7", "W2"), `severity` ("error" | "warning"),
    `path` (a concept path such as "node_fields/p", "" for the file) and a
    `message` saying what is wrong and what to do."""

    rule: str
    severity: str
    path: str
    message: str


@dataclass(frozen=True)
class Report:
    """Every finding of one validation."""

    findings: tuple[Finding, ...] = field(default_factory=tuple)

    @property
    def errors(self) -> list[Finding]:
        """The findings that make the file invalid."""
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> list[Finding]:
        """The findings a reader of a valid file should know."""
        return [f for f in self.findings if f.severity == "warning"]

    @property
    def ok(self) -> bool:
        """Whether the file has no errors."""
        return not self.errors

    @property
    def error_ids(self) -> list[str]:
        """The rules the errors break, each once: ["E7", ...]."""
        return sorted({f.rule for f in self.errors})

    @property
    def warning_ids(self) -> list[str]:
        """The rules the warnings name, each once."""
        return sorted({f.rule for f in self.warnings})


def validate(path: str) -> Report:
    """Checks the file at `path` against every rule it can decide."""
    handle = ctypes.c_void_p()
    call("gamut_validate", b(path), ctypes.byref(handle))
    try:
        out = []
        for i in range(_lib._lib.gamut_report_count(handle)):
            parts = [ctypes.c_char_p() for _ in range(4)]
            _lib._lib.gamut_report_get(handle, i, *[ctypes.byref(p) for p in parts])
            out.append(Finding(*[(p.value or b"").decode("utf-8", "replace") for p in parts]))
        return Report(tuple(out))
    finally:
        _lib._lib.gamut_report_free(handle)

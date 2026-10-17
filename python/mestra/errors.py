"""Errors and findings, each naming the rule it is about.

Every mistake this package can name carries the identifier of the rule
it breaks, so that a message can be traced to the specification.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["MestraError", "TooLarge", "Finding"]


class MestraError(Exception):
    """A rule broken by a file or by a call.

    `MestraError(rule, message, path)`: `rule` is the identifier
    ("E11"), `message` says what is wrong in plain words, and `path`
    names the object the mistake is about, a concept path such as
    `mesh/node_arrays/pressure` or the name an argument gave.

    `rule` is empty when the mistake is the caller's and not the
    file's: a slot named that is not in the file, an index array that
    is not strictly increasing. The identifiers stay for findings
    about a file, so that a caller who catches E05 catches a malformed
    file and not their own typo.
    """

    def __init__(self, rule: str, message: str, path: str = "") -> None:
        self.rule = rule
        self.message = message
        self.path = path
        super().__init__(": ".join(
            [part for part in (rule, path) if part] + [message]))


class TooLarge(MestraError):
    """A read that would materialise more than the limit allows.

    It is E41 when an eager read meets it. A validator catches it and
    leaves the rule unchecked instead, because the specification
    reserves the size case for an eager read.
    """

    def __init__(self, message: str, path: str = "",
                 count: int = 0) -> None:
        super().__init__("E41", message, path)
        self.count = count


@dataclass(frozen=True)
class Finding:
    """One validator outcome: a rule, where it applies, and why.

    `severity` is "error" or "warning"; left out, it follows from the
    rule's letter. Printed as `<rule> <path>: <message>`, which is the
    line every language's command-line tool prints.
    """

    rule: str
    path: str
    message: str
    severity: str = ""

    def __post_init__(self) -> None:
        if not self.severity:
            object.__setattr__(
                self, "severity",
                "warning" if self.rule.startswith("W") else "error")

    def __str__(self) -> str:
        head = " ".join(part for part in (self.rule, _one_line(self.path))
                        if part)
        if head:
            return "%s: %s" % (head, _one_line(self.message))
        return _one_line(self.message)


def _one_line(text: str) -> str:
    """A path or a message as part of one printed line: a control
    character, which an illegal name can hold, is written as \\xHH so
    that the finding stays on its line."""
    return "".join("\\x%02x" % ord(c) if ord(c) < 32 or ord(c) == 127
                   else c for c in text)

"""Reading the guide's pages for the tests that hold them to the examples."""

from __future__ import annotations

import pathlib
import re
import textwrap

ROOT = pathlib.Path(__file__).resolve().parents[2]
GUIDE = ROOT / "docs" / "guide"
EXAMPLES = ROOT / "examples"


def blocks(text: str, language: str) -> list[str]:
    """The fenced blocks of one language in a page."""
    return re.findall(rf"^```{language}\n(.*?)^```$", text, re.M | re.S)


def contiguous(part: str, whole: str) -> bool:
    """Whether `part` is consecutive lines of `whole`, an excerpt from inside
    a block shown with its indentation removed."""
    p = textwrap.dedent(part.rstrip("\n")).split("\n")
    w = whole.split("\n")
    return any(textwrap.dedent("\n".join(w[i:i + len(p)])).split("\n") == p
               for i in range(len(w) - len(p) + 1))

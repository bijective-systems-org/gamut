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


def sessions(text: str) -> list[tuple[str, list[str]]]:
    """(command, expected output lines) for each `$ ` line of a page's
    console blocks."""
    steps: list[tuple[str, list[str]]] = []
    for block in blocks(text, "console"):
        for line in block.rstrip("\n").split("\n"):
            if line.startswith("$ "):
                steps.append((line[2:], []))
            else:
                steps[-1][1].append(line)
    return steps


def matches(expected: str, got: str) -> bool:
    """Whether a printed line is the line shown, where `...` in the shown
    line stands for text that varies, such as a file's size."""
    pattern = ".*".join(re.escape(part) for part in expected.split("..."))
    return re.fullmatch(pattern, got) is not None


def contiguous(part: str, whole: str) -> bool:
    """Whether `part` is consecutive lines of `whole`, an excerpt from inside
    a block shown with its indentation removed."""
    p = textwrap.dedent(part.rstrip("\n")).split("\n")
    w = whole.split("\n")
    return any(textwrap.dedent("\n".join(w[i:i + len(p)])).split("\n") == p
               for i in range(len(w) - len(p) + 1))

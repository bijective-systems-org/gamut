"""Reading the guide's pages for the tests that hold them to the examples.

Run as a script, it checks what one language's examples printed against
the pages that show them, for the lanes that run those examples outside
pytest (MATLAB, Julia):

    python python/tests/_pages.py LANGUAGE FOLDER

where FOLDER holds each program's output as <name>.txt.
"""

from __future__ import annotations

import pathlib
import re
import sys
import textwrap

ROOT = pathlib.Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
GUIDE = DOCS / "guide"
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


# The programs a page is made from in each language but Python, whose
# example the page's number names. Its code blocks quote them; on a page
# with language tabs, an output block outside the tabs is what every
# language's program prints, and one inside a tab is what that language's
# prints.
PROGRAMS = {
    "guide/01-run-tables.md": {"matlab": ["matlab/run_table.m"], "julia": ["julia/run_table.jl"],
                               "cpp": ["cpp/run_table.cpp"]},
    "guide/02-one-mesh.md": {"matlab": ["matlab/one_mesh.m"], "julia": ["julia/one_mesh.jl"],
                             "cpp": ["cpp/one_mesh.cpp"]},
    "guide/07-models.md": {"matlab": ["matlab/Polynomial.m", "matlab/evaluate_model.m"],
                           "julia": ["julia/nearest.jl"]},
    "reference/matlab.md": {"matlab": ["matlab/read_with_ncread.m", "matlab/evaluate_model.m"]},
    "reference/julia.md": {"julia": ["julia/nearest.jl"]},
    "reference/c-and-cpp.md": {"cpp": ["cpp/nearest.cpp"], "c": ["c/one_mesh.c"]},
}
TABS = {"Python": "python", "MATLAB": "matlab", "Julia": "julia", "C++": "cpp", "C": "c"}


def outputs(text: str, language: str) -> list[str]:
    """The output blocks of a page with language tabs that `language`'s
    program prints: those outside the tabs, and those in its own tab."""
    shown, tab, block = [], None, None
    for line in text.split("\n"):
        if block is not None:
            if line == "```":
                if tab in (None, language):
                    shown.append("\n".join(block) + "\n")
                block = None
            else:
                block.append(line)
        elif line.startswith("/// tab | "):
            tab = TABS[line[len("/// tab | "):].strip()]
        elif line == "///":
            tab = None
        elif line == "```text":
            block = []
    return shown


def tabbed(text: str) -> bool:
    return "\n/// tab | " in text


def check(language: str, folder: pathlib.Path) -> list[str]:
    """What is wrong with the output of `language`'s programs, kept in
    `folder` as <name>.txt, against the tabbed pages they make."""
    problems = []
    for page, programs in PROGRAMS.items():
        text = (DOCS / page).read_text(encoding="utf-8")
        if language not in programs or not tabbed(text):
            continue
        printed = ""
        for program in programs[language]:
            kept = folder / (pathlib.Path(program).stem + ".txt")
            if not kept.is_file():
                problems.append(f"{page}: {program} was not run (no {kept})")
                continue
            printed += kept.read_text(encoding="utf-8")
        for block in outputs(text, language):
            if not contiguous(block, printed):
                problems.append(f"{page} shows output its {language} program does not print:\n{block}")
    return problems


if __name__ == "__main__":
    language, folder = sys.argv[1], pathlib.Path(sys.argv[2])
    found = check(language, folder)
    print("\n".join(found) or f"every page's {language} output is what its program prints")
    sys.exit(1 if found else 0)

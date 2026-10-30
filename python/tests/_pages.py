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
# example the page's number names. Its code blocks quote them, and its
# output blocks are what they print (see `outputs`). Every program a lane
# checks must have run, except the files a page quotes that print nothing.
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
QUOTED_ONLY = {"matlab/Polynomial.m"}       # a class the model example uses
TABS = {"Python": "python", "MATLAB": "matlab", "Julia": "julia", "C++": "cpp", "C": "c"}
CODE = set(TABS.values())


def outputs(text: str, language: str) -> list[str]:
    """The output blocks of a page that `language`'s program prints. An
    output block is printed by the code just before it: inside a language
    tab, that language's; after a set of tabs, every language in the set;
    elsewhere, the last code block's (a shell's output is no language's).
    One before any code is every language's. Tabs are one level deep."""
    shown: list[str] = []
    owners: set[str] = set(CODE)  # who prints the next output block outside tabs
    tab = None                  # the open tab's language
    tabs: set[str] | None = None  # the languages of the set of tabs being read
    fence, block = None, []
    for line in text.split("\n"):
        if fence is not None:
            if line == "```":
                if fence == "text" and language in ({tab} if tab else owners):
                    shown.append("\n".join(block) + "\n")
                elif tab is None:
                    owners = {fence}
                fence = None
            else:
                block.append(line)
        elif line.startswith("```"):
            fence, block = line[3:].strip(), []
            if tabs is not None and tab is None:    # the set of tabs has ended
                owners, tabs = tabs, None
        elif line.startswith("////"):
            raise ValueError("a page's language tabs are one level deep, not nested")
        elif line.startswith("/// tab | "):
            tab = TABS[line[len("/// tab | "):].strip()]
            tabs = (tabs or set()) | {tab}
        elif line == "///":
            tab = None
        elif line.strip() and tabs is not None and tab is None:
            owners, tabs = tabs, None
    return shown


def check(language: str, folder: pathlib.Path) -> list[str]:
    """What is wrong with the output of `language`'s programs, kept in
    `folder` as <name>.txt, against the pages that show them."""
    problems = []
    for page, programs in PROGRAMS.items():
        if language not in programs:
            continue
        text = (DOCS / page).read_text(encoding="utf-8")
        printed = ""
        for program in programs[language]:
            if program in QUOTED_ONLY:
                continue
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

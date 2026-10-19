"""The README quotes the examples exactly: its code blocks are lines of the
example scripts, each line of its side-by-side comparison is code from the
example in that language, and its output block is what the README's own
example prints."""

from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys

import pytest

from _pages import EXAMPLES, ROOT, blocks, contiguous

README = ROOT / "README.md"
SOURCES = {"python": sorted(EXAMPLES.glob("[0-9][0-9]_*.py")),
           "matlab": [EXAMPLES / "matlab" / "one_mesh.m"],
           "julia": [EXAMPLES / "julia" / "one_mesh.jl"],
           "cpp": [EXAMPLES / "cpp" / "one_mesh.cpp"]}

pytestmark = pytest.mark.skipif(not (README.is_file() and EXAMPLES.is_dir()),
                                reason="the README and examples are not beside this test (an installed package)")


@pytest.mark.parametrize("language", sorted(SOURCES))
def test_readme_quotes_the_examples(language):
    text = README.read_text(encoding="utf-8")
    sources = [p.read_text(encoding="utf-8") for p in SOURCES[language]]
    for block in blocks(text, language):
        assert any(contiguous(block, s) for s in sources), f"the README quotes {language} code no example has:\n{block}"


LABELS = {"Python": "python", "MATLAB": "matlab", "Julia": "julia", "C++": "cpp"}


def test_comparison_lines_are_code_from_the_examples():
    """Each "  Language   code" line of the comparison is code from that
    language's example; an ellipsis marks a shortened call, and the parts
    around it appear in order."""
    text = README.read_text(encoding="utf-8")
    lines = [m.groups() for block in blocks(text, "")
             for m in re.finditer(r"^  (Python|MATLAB|Julia|C\+\+) +(.+)$", block, re.M)]
    assert {label for label, _ in lines} == set(LABELS), "the comparison shows every language"
    for label, code in lines:
        source = "\n".join(p.read_text(encoding="utf-8") for p in SOURCES[LABELS[label]])
        at = 0
        for part in (piece.strip() for piece in code.split("…")):
            if not part:
                continue
            found = source.find(part, at)
            assert found >= 0, f"the comparison shows {label} code its example does not have: {part}"
            at = found + len(part)


def test_readme_output_is_what_its_example_prints(tmp_path):
    env = dict(os.environ)
    package = pathlib.Path(__file__).resolve().parents[1]
    import gamut
    if pathlib.Path(gamut.__file__).resolve().is_relative_to(package):
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(package), env.get("PYTHONPATH")]))
    result = subprocess.run([sys.executable, str(EXAMPLES / "00_readme.py")], cwd=tmp_path, env=env,
                            capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stderr
    for block in blocks(README.read_text(encoding="utf-8"), "text"):
        assert contiguous(block, result.stdout), f"the README shows output its example does not print:\n{block}"

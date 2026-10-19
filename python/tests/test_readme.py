"""The README quotes the examples exactly: its Python blocks are lines of the
example scripts, its MATLAB, Julia and C++ blocks lines of the language
examples, and its output block what the README's own example prints."""

from __future__ import annotations

import os
import pathlib
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
    shown = blocks(text, language)
    assert shown, f"the README shows {language} code"
    sources = [p.read_text(encoding="utf-8") for p in SOURCES[language]]
    for block in shown:
        assert any(contiguous(block, s) for s in sources), f"the README quotes {language} code no example has:\n{block}"


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

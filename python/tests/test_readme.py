"""The README quotes the examples exactly: its Python blocks are lines of the
example scripts, its MATLAB, Julia and C++ blocks lines of the language
examples, and its output blocks what those examples print: the sweep's
line (00_readme.py, and the MATLAB, Julia and C++ sweeps) and the model's
(07_models.py, and the MATLAB example that evaluates its file)."""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys

import pytest

from _pages import EXAMPLES, ROOT, blocks, contiguous

README = ROOT / "README.md"
SOURCES = {"python": sorted(EXAMPLES.glob("[0-9][0-9]_*.py")),
           "matlab": [EXAMPLES / "matlab" / "sweep.m", EXAMPLES / "matlab" / "evaluate_model.m"],
           "julia": [EXAMPLES / "julia" / "sweep.jl"],
           "cpp": [EXAMPLES / "cpp" / "sweep.cpp"]}

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


def _sweep_block():
    """The line all four sweeps print."""
    shown = [b for b in blocks(README.read_text(encoding="utf-8"), "text")
             if b.startswith("lift of the runs that converged:")]
    assert len(shown) == 1, "the README shows the sweep's line once"
    return shown[0]


def test_readme_output_is_what_its_examples_print(tmp_path):
    env = dict(os.environ)
    package = pathlib.Path(__file__).resolve().parents[1]
    import gamut
    if pathlib.Path(gamut.__file__).resolve().is_relative_to(package):
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(package), env.get("PYTHONPATH")]))
    printed = []
    for script in ("00_readme.py", "07_models.py"):
        result = subprocess.run([sys.executable, str(EXAMPLES / script)], cwd=tmp_path, env=env,
                                capture_output=True, text=True, timeout=300)
        assert result.returncode == 0, result.stderr
        printed.append(result.stdout)
    assert contiguous(_sweep_block(), printed[0]), "00_readme.py prints the sweep's line"
    for block in blocks(README.read_text(encoding="utf-8"), "text"):
        assert any(contiguous(block, out) for out in printed), \
            f"the README shows output its examples do not print:\n{block}"


def test_readme_cpp_example_prints_the_same(tmp_path):
    # MATLAB and Julia run their copies in their own lanes.
    if sys.platform.startswith("win") or shutil.which("c++") is None:
        pytest.skip("needs a compiler named c++")
    import gamut
    library = pathlib.Path(gamut.library_path())
    program = tmp_path / "sweep"
    subprocess.run(["c++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-pedantic",
                    str(EXAMPLES / "cpp" / "sweep.cpp"), f"-I{ROOT / 'include'}",
                    f"-L{library.parent}", "-lgamut", f"-Wl,-rpath,{library.parent}",
                    "-o", str(program)], check=True, capture_output=True)
    result = subprocess.run([str(program)], cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert contiguous(_sweep_block(), result.stdout), f"the C++ example does not print:\n{_sweep_block()}"

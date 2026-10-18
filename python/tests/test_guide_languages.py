"""The guide's MATLAB, Julia, and C++ and C pages quote their examples
exactly, and the C++ and C examples, built against the core this package
loaded, print what their page shows.  (MATLAB and Julia run their examples
in their own lanes.)"""

from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys

import pytest

import gamut
from _pages import EXAMPLES, GUIDE, ROOT, blocks, contiguous

PAGES = {"12-matlab.md": [("matlab", EXAMPLES / "matlab" / "one_mesh.m")],
         "13-julia.md": [("julia", EXAMPLES / "julia" / "one_mesh.jl")],
         "14-c-and-cpp.md": [("cpp", EXAMPLES / "cpp" / "one_mesh.cpp"),
                             ("c", EXAMPLES / "c" / "one_mesh.c")]}


@pytest.mark.skipif(not GUIDE.is_dir(), reason="the guide is not beside this test (an installed package)")
@pytest.mark.parametrize("page", sorted(PAGES))
def test_language_page_quotes_its_example(page):
    text = (GUIDE / page).read_text(encoding="utf-8")
    for language, example in PAGES[page]:
        source = example.read_text(encoding="utf-8")
        shown = blocks(text, language)
        assert shown, f"{page} shows {language} code"
        for block in shown:
            assert contiguous(block, source), f"{page} quotes code not in {example.name}:\n{block}"


@pytest.mark.skipif(not GUIDE.is_dir(), reason="the guide is not beside this test (an installed package)")
@pytest.mark.parametrize("compiler, flags, source",
                         [("cc", ["-std=c99"], EXAMPLES / "c" / "one_mesh.c"),
                          ("c++", ["-std=c++17"], EXAMPLES / "cpp" / "one_mesh.cpp")],
                         ids=["c", "cpp"])
def test_example_prints_what_its_page_shows(tmp_path, compiler, flags, source):
    if sys.platform.startswith("win") or shutil.which(compiler) is None:
        pytest.skip(f"needs a compiler named {compiler}")
    library = pathlib.Path(gamut.library_path())
    program = tmp_path / "one_mesh"
    subprocess.run([compiler, *flags, "-Wall", "-Wextra", "-Werror", "-pedantic",
                    str(source), f"-I{ROOT / 'include'}",
                    f"-L{library.parent}", "-lgamut", "-lm", f"-Wl,-rpath,{library.parent}",
                    "-o", str(program)], check=True, capture_output=True)
    result = subprocess.run([str(program)], cwd=tmp_path, capture_output=True, text=True,
                            timeout=120)
    assert result.returncode == 0, result.stderr
    text = (GUIDE / "14-c-and-cpp.md").read_text(encoding="utf-8")
    for block in blocks(text, "text"):
        assert contiguous(block, result.stdout), f"the page shows output the program does not print:\n{block}"

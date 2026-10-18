"""The MATLAB, Julia and C pages of the guide quote their examples exactly,
and the C example, built against the core this package loaded, prints what
its page shows.  (MATLAB and Julia run their examples in their own lanes.)"""

from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys

import pytest

import gamut
from _pages import EXAMPLES, GUIDE, ROOT, blocks, contiguous

PAGES = {"12-matlab.md": ("matlab", EXAMPLES / "matlab" / "one_mesh.m"),
         "13-julia.md": ("julia", EXAMPLES / "julia" / "one_mesh.jl"),
         "14-c-and-cpp.md": ("c", EXAMPLES / "c" / "one_mesh.c")}


@pytest.mark.skipif(not GUIDE.is_dir(), reason="the guide is not beside this test (an installed package)")
@pytest.mark.parametrize("page", sorted(PAGES))
def test_language_page_quotes_its_example(page):
    language, example = PAGES[page]
    text = (GUIDE / page).read_text(encoding="utf-8")
    source = example.read_text(encoding="utf-8")
    shown = blocks(text, language)
    assert shown, f"{page} shows {language} code"
    for block in shown:
        assert contiguous(block, source), f"{page} quotes code not in {example.name}:\n{block}"


@pytest.mark.skipif(not GUIDE.is_dir(), reason="the guide is not beside this test (an installed package)")
@pytest.mark.skipif(sys.platform.startswith("win") or shutil.which("cc") is None,
                    reason="needs a C compiler named cc")
def test_c_example_prints_what_its_page_shows(tmp_path):
    library = pathlib.Path(gamut.library_path())
    program = tmp_path / "one_mesh"
    subprocess.run(["cc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic",
                    str(EXAMPLES / "c" / "one_mesh.c"), f"-I{ROOT / 'include'}",
                    f"-L{library.parent}", "-lgamut", "-lm", f"-Wl,-rpath,{library.parent}",
                    "-o", str(program)], check=True, capture_output=True)
    result = subprocess.run([str(program)], cwd=tmp_path, capture_output=True, text=True,
                            timeout=120)
    assert result.returncode == 0, result.stderr
    text = (GUIDE / "14-c-and-cpp.md").read_text(encoding="utf-8")
    for block in blocks(text, "text"):
        assert contiguous(block, result.stdout), f"the page shows output the program does not print:\n{block}"

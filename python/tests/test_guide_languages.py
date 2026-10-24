"""The guide's pages quote their MATLAB, Julia, C++ and C examples exactly,
and the C++ and C examples, built against the core this package loaded,
print what their page shows.  (MATLAB and Julia run their examples in
their own lanes.)"""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys

import pytest

import gamut
from _pages import EXAMPLES, GUIDE, ROOT, blocks, contiguous

PAGES = {"07-models.md": [("matlab", [EXAMPLES / "matlab" / "Polynomial.m",
                                      EXAMPLES / "matlab" / "evaluate_model.m"]),
                          ("julia", [EXAMPLES / "julia" / "nearest.jl"])],
         "12-matlab.md": [("matlab", [EXAMPLES / "matlab" / "sweep.m", EXAMPLES / "matlab" / "one_mesh.m",
                                      EXAMPLES / "matlab" / "read_with_ncread.m",
                                      EXAMPLES / "matlab" / "evaluate_model.m"])],
         "13-julia.md": [("julia", [EXAMPLES / "julia" / "sweep.jl", EXAMPLES / "julia" / "one_mesh.jl",
                                    EXAMPLES / "julia" / "nearest.jl"])],
         "14-c-and-cpp.md": [("cpp", [EXAMPLES / "cpp" / "sweep.cpp", EXAMPLES / "cpp" / "one_mesh.cpp",
                                      EXAMPLES / "cpp" / "nearest.cpp"]),
                             ("c", [EXAMPLES / "c" / "one_mesh.c"])]}


@pytest.mark.skipif(not GUIDE.is_dir(), reason="the guide is not beside this test (an installed package)")
@pytest.mark.parametrize("page", sorted(PAGES))
def test_language_page_quotes_its_example(page):
    text = (GUIDE / page).read_text(encoding="utf-8")
    for language, examples in PAGES[page]:
        sources = [e.read_text(encoding="utf-8") for e in examples]
        shown = blocks(text, language)
        assert shown, f"{page} shows {language} code"
        for block in shown:
            assert any(contiguous(block, source) for source in sources), \
                f"{page} quotes {language} code no example has:\n{block}"


@pytest.mark.skipif(not GUIDE.is_dir(), reason="the guide is not beside this test (an installed package)")
def test_examples_print_what_their_page_shows(tmp_path):
    if sys.platform.startswith("win") or not (shutil.which("cc") and shutil.which("c++")):
        pytest.skip("needs compilers named cc and c++")
    library = pathlib.Path(gamut.library_path())
    # nearest.cpp evaluates the model file examples/07_models.py writes.
    env = dict(os.environ)
    package = pathlib.Path(__file__).resolve().parents[1]
    if pathlib.Path(gamut.__file__).resolve().is_relative_to(package):
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(package), env.get("PYTHONPATH")]))
    subprocess.run([sys.executable, str(EXAMPLES / "07_models.py")], cwd=tmp_path, env=env,
                   check=True, capture_output=True, timeout=300)
    printed = []
    for compiler, flags, source in [("cc", ["-std=c99"], EXAMPLES / "c" / "one_mesh.c"),
                                    ("c++", ["-std=c++17"], EXAMPLES / "cpp" / "one_mesh.cpp"),
                                    ("c++", ["-std=c++17"], EXAMPLES / "cpp" / "sweep.cpp"),
                                    ("c++", ["-std=c++17"], EXAMPLES / "cpp" / "nearest.cpp")]:
        program = tmp_path / f"{source.stem}_{source.suffix[1:]}"
        subprocess.run([compiler, *flags, "-Wall", "-Wextra", "-Werror", "-pedantic",
                        str(source), f"-I{ROOT / 'include'}",
                        f"-L{library.parent}", "-lgamut", "-lm", f"-Wl,-rpath,{library.parent}",
                        "-o", str(program)], check=True, capture_output=True)
        result = subprocess.run([str(program)], cwd=tmp_path, capture_output=True, text=True,
                                timeout=120)
        assert result.returncode == 0, f"{source.name}: {result.stderr}"
        printed.append(result.stdout)
    text = (GUIDE / "14-c-and-cpp.md").read_text(encoding="utf-8")
    for block in blocks(text, "text"):
        assert any(contiguous(block, out) for out in printed), \
            f"the page shows output no example prints:\n{block}"

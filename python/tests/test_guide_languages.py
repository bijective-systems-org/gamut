"""The guide's pages quote their MATLAB, Julia, C++ and C examples exactly,
and the C++ and C examples, built against the core this package loaded,
print what their pages show.  (MATLAB and Julia run their examples in
their own lanes, and check them with `python _pages.py`.)"""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys

import pytest

import gamut
from _pages import DOCS, EXAMPLES, PROGRAMS, ROOT, blocks, check, contiguous

# The examples each page quotes, by language (Python's are held to their
# pages by test_examples).
PAGES = {page: [(language, [EXAMPLES / p for p in programs])
                for language, programs in by_language.items()]
         for page, by_language in PROGRAMS.items()}


@pytest.mark.skipif(not DOCS.is_dir(), reason="the guide is not beside this test (an installed package)")
@pytest.mark.parametrize("page", sorted(PAGES))
def test_language_page_quotes_its_example(page):
    text = (DOCS / page).read_text(encoding="utf-8")
    for language, examples in PAGES[page]:
        sources = [e.read_text(encoding="utf-8") for e in examples]
        shown = blocks(text, language)
        assert shown, f"{page} shows {language} code"
        for block in shown:
            assert any(contiguous(block, source) for source in sources), \
                f"{page} quotes {language} code no example has:\n{block}"


@pytest.mark.skipif(not DOCS.is_dir(), reason="the guide is not beside this test (an installed package)")
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
    printed = {}
    for source in sorted({EXAMPLES / p for by_language in PROGRAMS.values()
                          for language, programs in by_language.items() if language in ("c", "cpp")
                          for p in programs}):
        compiler, flags = ("cc", ["-std=c99"]) if source.suffix == ".c" else ("c++", ["-std=c++17"])
        program = tmp_path / f"{source.stem}_{source.suffix[1:]}"
        subprocess.run([compiler, *flags, "-Wall", "-Wextra", "-Werror", "-pedantic",
                        str(source), f"-I{ROOT / 'include'}",
                        f"-L{library.parent}", "-lgamut", "-lm", f"-Wl,-rpath,{library.parent}",
                        "-o", str(program)], check=True, capture_output=True)
        directory = tmp_path / (program.name + "_files")
        directory.mkdir()
        if source.stem == "nearest":
            for model in tmp_path.glob("*.gamut"):
                shutil.copy2(model, directory / model.name)
        result = subprocess.run([str(program)], cwd=directory, capture_output=True, text=True,
                                timeout=120)
        assert result.returncode == 0, f"{source.name}: {result.stderr}"
        printed[source] = result.stdout
    for language, suffix in (("cpp", ".cpp"), ("c", ".c")):
        kept = tmp_path / f"printed_{language}"
        kept.mkdir()
        for source, out in printed.items():
            if source.suffix == suffix:
                (kept / f"{source.stem}.txt").write_text(out, encoding="utf-8")
        problems = check(language, kept)
        assert not problems, "\n".join(problems)

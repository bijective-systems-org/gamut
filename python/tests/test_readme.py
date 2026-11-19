"""The project README quotes the first Python example and its output."""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import pytest

from _pages import EXAMPLES, ROOT, blocks, contiguous

README = ROOT / "README.md"
SCRIPT = EXAMPLES / "00_readme.py"


@pytest.mark.skipif(not (README.is_file() and SCRIPT.is_file()),
                    reason="the README and example are not beside this test (an installed package)")
def test_readme_matches_the_first_example(tmp_path):
    text = README.read_text(encoding="utf-8")
    shown = blocks(text, "python")
    assert shown and all(contiguous(block, SCRIPT.read_text(encoding="utf-8")) for block in shown)

    env = dict(os.environ)
    package = pathlib.Path(__file__).resolve().parents[1]
    import gamut
    if pathlib.Path(gamut.__file__).resolve().is_relative_to(package):
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(package), env.get("PYTHONPATH")]))
    result = subprocess.run([sys.executable, str(SCRIPT)], cwd=tmp_path, env=env,
                            capture_output=True, text=True, check=True, timeout=300)
    expected = blocks(text, "text")
    assert expected and all(contiguous(block, result.stdout) for block in expected)

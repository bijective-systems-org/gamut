"""Every script in examples/ runs from a clean directory and exits cleanly,
and the guide page with its number quotes it exactly: each code block is
lines of the script, each output block lines of what it prints, and each
`$ gamut` line, run in the folder the script wrote, prints what is shown."""

from __future__ import annotations

import os
import pathlib
import shlex
import subprocess
import sys

import pytest

from _pages import EXAMPLES, GUIDE, blocks, contiguous, matches, outputs, sessions
from gamut import cli

SCRIPTS = sorted(p for p in EXAMPLES.glob("[0-9][0-9]_*.py")) if EXAMPLES.is_dir() else []
NEEDS = {"08_selecting_parts.py": "pint", "10_vtk.py": "pyvista"}


@pytest.mark.skipif(not SCRIPTS, reason="examples/ is not beside this test (an installed package)")
@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.stem)
def test_example_runs(script, tmp_path, capsys, monkeypatch):
    if script.name in NEEDS:
        pytest.importorskip(NEEDS[script.name])
    env = dict(os.environ)
    package = pathlib.Path(__file__).resolve().parents[1]
    import gamut
    if pathlib.Path(gamut.__file__).resolve().is_relative_to(package):
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(package), env.get("PYTHONPATH")]))
    result = subprocess.run([sys.executable, str(script)], cwd=tmp_path, env=env,
                            capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip(), "an example says what it did"

    for page in GUIDE.glob(script.name[:2] + "-*.md"):
        text = page.read_text(encoding="utf-8")
        source = script.read_text(encoding="utf-8")
        assert f"examples/{script.name}" in text, f"{page.name} names its script"
        for block in blocks(text, "python"):
            assert contiguous(block, source), f"{page.name} quotes code not in {script.name}:\n{block}"
        for block in outputs(text, "python"):
            assert contiguous(block, result.stdout), \
                f"{page.name} shows output {script.name} does not print:\n{block}"
        monkeypatch.chdir(tmp_path)
        for command, expected in sessions(text):
            argv = shlex.split(command)
            assert argv[0] == "gamut", command
            cli.main(argv[1:])
            got = capsys.readouterr().out.rstrip("\n").split("\n")
            assert len(got) == len(expected) and all(map(matches, expected, got)), \
                f"{page.name}: $ {command}\nshown:\n" + "\n".join(expected) + "\ngot:\n" + "\n".join(got)

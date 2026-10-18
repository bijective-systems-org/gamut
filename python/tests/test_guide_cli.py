"""The command-line page of the guide runs as written: every `$ gamut`
line gives the output shown under it (`...` stands for text that varies,
such as a file's size), and every document it shows is the one in
examples/cli."""

from __future__ import annotations

import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys

import pytest

from _pages import EXAMPLES, GUIDE, ROOT, blocks
from gamut import cli

PAGE = GUIDE / "11-command-line.md"
DOCUMENTS = EXAMPLES / "cli"


def _session(block: str) -> list[tuple[str, list[str]]]:
    """(command, expected output lines) for each `$ ` line of a block."""
    steps: list[tuple[str, list[str]]] = []
    for line in block.rstrip("\n").split("\n"):
        if line.startswith("$ "):
            steps.append((line[2:], []))
        else:
            steps[-1][1].append(line)
    return steps


def _matches(expected: str, got: str) -> bool:
    pattern = ".*".join(re.escape(part) for part in expected.split("..."))
    return re.fullmatch(pattern, got) is not None


@pytest.mark.skipif(not PAGE.exists(), reason="the guide is not beside this test (an installed package)")
def test_the_command_line_page_runs(tmp_path, capsys, monkeypatch):
    env = dict(os.environ)
    package = pathlib.Path(__file__).resolve().parents[1]
    import gamut
    if pathlib.Path(gamut.__file__).resolve().is_relative_to(package):
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(package), env.get("PYTHONPATH")]))
    for script in ("01_run_table.py", "02_one_mesh.py"):
        subprocess.run([sys.executable, str(ROOT / "examples" / script)], cwd=tmp_path, env=env,
                       check=True, capture_output=True)
    for document in DOCUMENTS.iterdir():
        shutil.copy(document, tmp_path)
    monkeypatch.chdir(tmp_path)

    text = PAGE.read_text(encoding="utf-8")
    shown = {p.name: p.read_text(encoding="utf-8") for p in DOCUMENTS.iterdir()}
    for language in ("json", "csv"):
        for block in blocks(text, language):
            assert block in shown.values(), f"the page shows a document not in examples/cli:\n{block}"

    steps = [s for block in blocks(text, "console") for s in _session(block)]
    assert steps, "the page has sessions"
    for command, expected in steps:
        argv = shlex.split(command)
        assert argv[0] == "gamut", command
        cli.main(argv[1:])
        got = capsys.readouterr().out.rstrip("\n").split("\n")
        assert len(got) == len(expected) and all(map(_matches, expected, got)), \
            f"$ {command}\nshown:\n" + "\n".join(expected) + "\ngot:\n" + "\n".join(got)

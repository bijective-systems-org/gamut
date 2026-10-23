"""The command-line page of the guide runs as written: every `$ gamut`
line gives the output shown under it (`...` stands for text that varies,
such as a file's size), and every document it shows is the one in
examples/cli."""

from __future__ import annotations

import os
import pathlib
import shlex
import shutil
import subprocess
import sys

import pytest

from _pages import EXAMPLES, GUIDE, ROOT, blocks, matches, sessions
from gamut import cli

PAGE = GUIDE / "11-command-line.md"
DOCUMENTS = EXAMPLES / "cli"


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

    steps = sessions(text)
    assert steps, "the page has sessions"
    for command, expected in steps:
        argv = shlex.split(command)
        assert argv[0] == "gamut", command
        cli.main(argv[1:])
        got = capsys.readouterr().out.rstrip("\n").split("\n")
        assert len(got) == len(expected) and all(map(matches, expected, got)), \
            f"$ {command}\nshown:\n" + "\n".join(expected) + "\ngot:\n" + "\n".join(got)

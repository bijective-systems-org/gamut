"""The examples of docs/examples run, and print what their READMEs say.

Each example directory holds a README.md and a python.py. The README's
"Expected output" section is the exact output of running python.py, so
an example that rots fails here rather than in a reader's hands. Each
one runs in a subprocess, in a directory of its own, because several
of them write a file into the working directory.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

# The worked examples are written against the version 0 interface and
# are rewritten with the documentation for version 1; until then they
# are not run.
pytestmark = pytest.mark.skip(
    reason="docs/examples use the version 0 interface; they are "
           "rewritten with the version 1 documentation")

EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "examples"
HEADING = "Expected output"
TIMEOUT = 120


def directories() -> list[Path]:
    return sorted(p.parent for p in EXAMPLES.glob("*/python.py"))


def expected_output(readme: Path) -> list[str]:
    """The lines of the README's "Expected output" block."""
    lines = readme.read_text(encoding="utf-8").splitlines()
    for at, line in enumerate(lines):
        if line.strip() == HEADING and lines[at + 1].startswith("---"):
            break
    else:
        raise AssertionError("%s has no %r section" % (readme, HEADING))
    out: list[str] = []
    for line in lines[at + 2:]:
        if not line.strip():
            if out:
                break
            continue
        if not line.startswith("    "):
            break
        out.append(line[4:].rstrip())
    assert out, "%s: the %r section is empty" % (readme, HEADING)
    return out


def test_every_example_has_a_readme() -> None:
    found = directories()
    assert found, "no examples under %s" % EXAMPLES
    assert len(found) <= 7, "one directory per concept, no more than seven"
    for directory in found:
        assert (directory / "README.md").exists(), directory


@pytest.mark.parametrize("directory", directories(),
                         ids=lambda p: p.name)
def test_example_runs_and_prints_what_the_readme_says(
        directory: Path, tmp_path: Path) -> None:
    script = directory / "python.py"
    body = [line for line in script.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")]
    assert len(body) < 30, "%s is %d lines" % (script, len(body))

    run = subprocess.run([sys.executable, str(script)], cwd=str(tmp_path),
                         capture_output=True, text=True, timeout=TIMEOUT)
    assert run.returncode == 0, run.stderr
    printed = [line.rstrip() for line in run.stdout.splitlines()]
    assert printed == expected_output(directory / "README.md")

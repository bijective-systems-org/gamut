"""Every script in examples/ runs from a clean directory and exits cleanly."""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import pytest

EXAMPLES = pathlib.Path(__file__).resolve().parents[2] / "examples"
SCRIPTS = sorted(p for p in EXAMPLES.glob("[0-9][0-9]_*.py")) if EXAMPLES.is_dir() else []
NEEDS = {"08_selecting_parts.py": "pint", "10_vtk.py": "pyvista"}


@pytest.mark.skipif(not SCRIPTS, reason="examples/ is not beside this test (an installed package)")
@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.stem)
def test_example_runs(script, tmp_path):
    if script.name in NEEDS:
        pytest.importorskip(NEEDS[script.name])
    env = dict(os.environ)
    package = pathlib.Path(__file__).resolve().parents[1]
    import mestra
    if pathlib.Path(mestra.__file__).resolve().is_relative_to(package):
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(package), env.get("PYTHONPATH")]))
    result = subprocess.run([sys.executable, str(script)], cwd=tmp_path, env=env,
                            capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip(), "an example says what it did"

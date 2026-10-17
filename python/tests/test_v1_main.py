"""``python -m mestra`` runs the command line."""

import subprocess
import sys


def test_python_dash_m_runs_the_command_line():
    out = subprocess.run([sys.executable, "-m", "mestra", "--help"],
                         capture_output=True, text=True)
    assert out.returncode == 0
    assert "validate" in out.stdout

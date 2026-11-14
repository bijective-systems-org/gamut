"""Appending in sessions (spec section 11.5): a writer stopped partway
leaves the file as it was, readers keep reading it, one session at a time."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap

import pytest

import gamut


def table(path, runs):
    with gamut.create(path, writer="t", parameters={"a": "1"},
                      labels={"member": {"role": "group", "categories": []}},
                      scalars={"cl": "1"}) as s:
        for i in range(runs):                    # one run at a time, as the README writes
            s.add_run({"a": float(i), "member": f"m{i % 7}", "cl": float(i)})


def beside(path):
    folder, name = os.path.split(os.path.abspath(path))
    return sorted(f for f in os.listdir(folder) if f.startswith(name + ".appending"))


def test_a_killed_append_leaves_the_file_as_it_was(tmp_path):
    p = str(tmp_path / "c.gamut")
    table(p, 3000)
    child = subprocess.Popen([sys.executable, "-c", textwrap.dedent(f"""
        import gamut
        s = gamut.open({p!r}, mode="a")
        i = 0
        while True:
            s.add_run({{"a": float(i), "member": "m1", "cl": float(i)}})
            if i == 100:
                print("appending", flush=True)
            i += 1
        """)], stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "appending"
    finally:
        child.kill()
        child.wait()
    assert not gamut.validate(p).findings
    with gamut.open(p) as s:
        assert s.row_count == 3000
        assert s.get_scalar("cl")[:3].tolist() == [0.0, 1.0, 2.0]
    assert beside(p)                              # the stopped session's lock and copy
    with gamut.open(p, mode="a") as s:            # the next session removes them
        s.add_run({"a": 1.0, "member": "m1", "cl": 1.0})
    assert beside(p) == []
    with gamut.open(p) as s:
        assert s.row_count == 3001


def test_one_session_at_a_time_and_readers_keep_the_file(tmp_path):
    p = str(tmp_path / "t.gamut")
    table(p, 2)
    with gamut.open(p, mode="a") as s:
        s.add_run({"a": 9.0, "member": "m0", "cl": 9.0})
        with gamut.open(p) as r:
            assert r.row_count == 2
        with pytest.raises(gamut.GamutError, match="being appended to by another session"):
            gamut.open(p, mode="a")
    with gamut.open(p) as r:
        assert r.row_count == 3
    assert beside(p) == []


def test_an_error_inside_append_keeps_the_runs_before_it(tmp_path):
    # Leaving the block on an error finishes the session, as it always has:
    # the runs added before the error are kept.
    p = str(tmp_path / "e.gamut")
    table(p, 2)
    with pytest.raises(RuntimeError):
        with gamut.open(p, mode="a") as s:
            s.add_run({"a": 9.0, "member": "m0", "cl": 9.0})
            raise RuntimeError("stop")
    with gamut.open(p) as r:
        assert r.row_count == 3
    assert beside(p) == []

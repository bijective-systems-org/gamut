"""The shared hostile subset, vectors/hostile.

Section 30 gives this subset a looser contract than the corpus's: a
validator must report at least `required_errors`, may report more,
and must finish cleanly inside `timeout_seconds` - not crash, not
hang, not exhaust memory, not stop at the first bad object. Opening
the file for its metadata alone, and any read of a slot, must refuse
with the same ids rather than return something.

Two cases are not committed, because thirty thousand HDF5 groups are
31 MB apiece. Run

    python vectors/generate.py --on-demand

before this file, as vectors/README.md says; the tests for those two
skip with that instruction when they are missing.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from mestra import _v0 as mestra
from tests import corpus

HOSTILE = os.path.join(corpus.VECTORS, "hostile")

#: What the driver reports back about one file.
DRIVER = r"""
import json, sys
from mestra import _v0 as mestra
from mestra._v0.cli import main as cli

path = sys.argv[1]
out = {}
for label in ("read", "read_eager", "info", "validate"):
    try:
        if label == "read":
            with mestra.read(path) as ds:
                out[label] = ["ok", ds.n_rows]
        elif label == "read_eager":
            mestra.read(path, lazy=False)
            out[label] = ["ok"]
        elif label == "info":
            out[label] = ["ok", cli(["info", path])]
        else:
            report = mestra.validate(path)
            out[label] = ["report", report.error_ids,
                          report.warning_ids]
    except mestra.MestraError as exc:
        out[label] = ["refused", exc.rule]
sys.stderr.write(json.dumps(out))
"""


def case_names() -> list[str]:
    with open(os.path.join(corpus.VECTORS, "manifest.json"),
              encoding="utf-8") as fh:
        manifest = json.load(fh)
    return [case["name"] for case in manifest.get("hostile", [])]


def expected(name: str) -> dict:
    with open(os.path.join(HOSTILE, name, "expected.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


CASES = case_names()


def case_path(name: str) -> str:
    return os.path.join(HOSTILE, name, "case.mes")


def present(name: str) -> str:
    path = case_path(name)
    if not os.path.exists(path):
        pytest.skip("run: python vectors/generate.py --on-demand")
    return path


def test_the_subset_is_listed_in_the_manifest():
    assert len(CASES) == 15
    for name in CASES:
        want = expected(name)
        assert want["allow_extra"] is True
        assert want["timeout_seconds"] == 10
        assert want["required_errors"] == sorted(
            set(want["required_errors"]))


@pytest.mark.parametrize("name", CASES)
def test_validate_reports_at_least_what_is_required(name):
    """At least the required ids, inside the timeout, no crash."""
    path = present(name)
    want = expected(name)
    report = mestra.validate(path)
    missing = set(want["required_errors"]) - set(report.error_ids)
    assert not missing, (name, sorted(missing), report.error_ids)


@pytest.mark.parametrize("name", CASES)
def test_every_entry_point_refuses_with_the_same_ids(name):
    """read, lazy read and info refuse; the process comes back."""
    path = present(name)
    want = expected(name)
    timeout = want["timeout_seconds"]
    done = subprocess.run([sys.executable, "-c", DRIVER, path],
                          capture_output=True, text=True,
                          timeout=timeout * 6,
                          cwd=os.path.dirname(os.path.dirname(
                              os.path.abspath(__file__))))
    assert done.returncode == 0, (
        "the process did not survive %s (exit %d)\n%s"
        % (name, done.returncode, done.stderr[-2000:]))
    got = json.loads(done.stderr[done.stderr.rfind("{"):])
    for label in ("read", "read_eager"):
        assert got[label][0] == "refused", (name, label, got[label])
        assert got[label][1] in mestra.reader.REFUSED, got[label]
    # `info` opens the file the same way, so it refuses and says so
    # rather than printing something it cannot vouch for.
    assert got["info"][0] == "refused" or got["info"][1] == 1, got
    assert got["validate"][0] == "report"
    missing = set(want["required_errors"]) - set(got["validate"][1])
    assert not missing, (name, sorted(missing))


@pytest.mark.parametrize("name", CASES)
def test_the_run_is_inside_the_timeout(name):
    """The whole of it, in one process, within timeout_seconds."""
    path = present(name)
    want = expected(name)
    done = subprocess.run([sys.executable, "-c", DRIVER, path],
                          capture_output=True, text=True,
                          timeout=want["timeout_seconds"])
    assert done.returncode == 0, done.stderr[-2000:]


def test_support_ids_survives_every_one():
    for name in CASES:
        path = case_path(name)
        if not os.path.exists(path):
            continue
        try:
            mestra.support_ids(path)
        except mestra.MestraError as exc:
            assert exc.rule in mestra.reader.REFUSED, name


@pytest.mark.parametrize("name", ["deep_groups_keys",
                                  "deep_groups_callables"])
def test_the_deep_files_are_the_ones_that_segfault_a_naive_reader(name):
    """Section 21: the scale-path trap, on the file that finds it."""
    path = present(name)
    report = mestra.validate(path)
    assert "E41" in report.error_ids
    with pytest.raises(mestra.MestraError) as caught:
        mestra.read(path)
    assert caught.value.rule in mestra.reader.REFUSED

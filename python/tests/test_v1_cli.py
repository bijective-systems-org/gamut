"""The command line: validate, info and upgrade, plain and `--json`."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import h5py
import pytest

from mestra.cli import main
from mestra.encoding import write_string_attr
from tests.v1_cases import CASES, lib

KEYS = ["kind", "addons", "file", "format", "findings", "errors",
        "warnings"]


@pytest.fixture
def family(tmp_path):
    path = str(tmp_path / "family.mes")
    lib.write(CASES["family"](), path)
    return path


def run_json(capsys, *argv):
    status = main(list(argv))
    return status, json.loads(capsys.readouterr().out)


def test_validate_prints_findings_and_totals(family, capsys):
    assert main(["validate", family]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("W02 labels/status: ")
    assert out[-1] == "0 error(s), 1 warning(s)"


def test_validate_json_follows_the_schema(family, capsys):
    status, document = run_json(capsys, "validate", family, "--json")
    assert status == 0
    assert list(document)[:len(KEYS)] == KEYS
    assert document["kind"] == "mesh" and document["addons"] == []
    assert document["format"] == "mestra/1"
    assert document["errors"] == 0 and document["warnings"] == 1
    assert document["findings"] == [{
        "rule": "W02", "severity": "warning", "path": "labels/status",
        "message": document["findings"][0]["message"]}]


def test_validate_exits_non_zero_on_an_error(family, capsys):
    with h5py.File(family, "r+") as f:
        write_string_attr(f["cl"], "units", "m per")
    status, document = run_json(capsys, "validate", family, "--json")
    assert status == 1
    assert document["errors"] == 1
    assert document["findings"][0]["rule"] == "E11"
    assert document["findings"][0]["severity"] == "error"


def test_info_prints_kind_and_addons_first(tmp_path, capsys):
    path = str(tmp_path / "model.mes")
    lib.write(CASES["model"](), path)
    assert main(["info", path]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "kind mesh, add-ons: uncertainty, model"
    assert "mestra/1" in out[1]
    assert any("served by m1" in line for line in out)


def test_info_json_describes_the_file(family, capsys):
    status, document = run_json(capsys, "info", family, "--json")
    assert status == 0
    assert list(document)[:2] == ["kind", "addons"]
    assert [p["name"] for p in document["parameters"]] == ["mach"]
    assert [lab["name"] for lab in document["labels"]] == [
        "member", "run", "split", "status"]
    assert document["labels"][0]["entries"] == ["m_a", "m_b", "m_c"]
    assert [s["name"] for s in document["scalars"]] == ["cl"]
    mesh = document["mesh"]
    assert mesh["kind"] == "mesh" and mesh["n_nodes"] == 6
    assert [a["name"] for a in mesh["node_arrays"]] == ["face", "pressure"]
    assert [a["name"] for a in mesh["cell_arrays"]] == [
        "face", "flagged", "velocity"]
    assert mesh["coordinates"]["varies"] == "group:member"
    assert document["rows"] == 6


def test_info_reports_foreign_content_as_w11(family, capsys):
    """What a tool asks of a file it did not write: the W11 findings
    name where the unknown attribute or group is."""
    with h5py.File(family, "r+") as f:
        f.create_group("vendor")
    status, document = run_json(capsys, "validate", family, "--json")
    w11 = [x for x in document["findings"] if x["rule"] == "W11"]
    assert w11 == [{"rule": "W11", "severity": "warning", "path": "vendor",
                    "message": "this reader does not know the group "
                               "vendor, and ignores it"}]


def test_a_version_0_file_is_named_for_upgrade(tmp_path, capsys):
    from mestra import _v0
    ds = _v0.Dataset(writer="v0", created="2026-10-16T00:00:00Z")
    ds.add_key("x", [1.0, 2.0], role="design", units="m")
    ds.add_scalar("y", [3.0, 4.0], units="1")
    old = str(tmp_path / "old.mes")
    _v0.write(ds, old)
    status, document = run_json(capsys, "validate", old, "--json")
    assert status == 1
    assert document["format"] == "mestra/0" and document["kind"] is None
    assert "upgrade" in document["findings"][0]["message"]
    new = str(tmp_path / "new.mes")
    status, document = run_json(capsys, "upgrade", old, new, "--json")
    assert status == 0 and os.path.exists(new)
    assert document["source"] == old and document["file"] == new
    assert document["kind"] == "table" and document["format"] == "mestra/1"
    assert document["errors"] == 0
    assert [x["rule"] for x in document["findings"]] == [""]
    assert main(["upgrade", old, str(tmp_path / "plain.mes")]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("dropped the root attribute aligned")
    assert out[-1] == "0 error(s), 1 warning(s)"


def test_a_refused_upgrade_exits_non_zero(family, tmp_path, capsys):
    status, document = run_json(capsys, "upgrade", family,
                                str(tmp_path / "x.mes"), "--json")
    assert status == 1
    assert "already version 1" in document["findings"][0]["message"]


def test_the_installed_command_runs(family):
    done = subprocess.run([sys.executable, "-m", "mestra.cli", "validate",
                           family, "--json"], capture_output=True,
                          text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["kind"] == "mesh"

"""Version 0 files upgraded to version 1.

The upgrade runs on the files that exist: the worked examples, the
clean cases of the version 0 corpus, and, where this machine has them,
TopoLink's capsule and aeroshell families and romlib's workflow
artifacts (read-only inputs; skipped cleanly where absent). Every
output must validate with no error, and the source is never changed.
Hand-built version 0 files pin each line of the conversion and each
refusal.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import h5py
import numpy as np
import pytest

from mestra import _v0
from mestra.codec import RESERVED, RESERVED_V0, decode_dict
from tests.v1_cases import assert_this_package, lib

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = sorted((ROOT / "docs" / "examples").glob("*.mes"))
CORPUS = ROOT / "vectors" / "cases"
DESKTOP = ROOT.parents[1]
TOPOLINK = DESKTOP / "topolink" / "geometries" / "families"
FAMILIES = [TOPOLINK / "capsule" / "capsule.mes",
            TOPOLINK / "mars_aeroshell" / "mars_aeroshell.mes"]
ROMLIB = DESKTOP / "romlib" / "examples" / "workflow"

#: The clean corpus cases version 1 cannot hold, and why.
REFUSED = {
    "derived_displacement": "derived array",
    "draws_and_summaries": "draws",
    "draws_shared": "draws",
    "two_supports_one_served": "supports",
    "two_supports_row_varying": "supports",
    "two_supports_unaligned": "supports",
    "warn_w05": "supports",
    "warn_w15": "supports",
    "zero_rows_unaligned": "supports",
    "warn_w10": "E11",
    "warn_w10_dangling_per": "E11",
}


def digest(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def clean_corpus_cases() -> list[str]:
    out = []
    for case in sorted(os.listdir(CORPUS)):
        expected = json.loads((CORPUS / case / "expected.json").read_text())
        if not expected["validator"]["errors"] and \
                (CORPUS / case / "case.mes").exists():
            out.append(case)
    return out


def romlib_files() -> list[Path]:
    return sorted(ROMLIB.rglob("*.mes")) if ROMLIB.is_dir() else []


def tagged(value):
    """A dictionary in a form where equal means equal in type, dtype,
    shape and bytes."""
    if isinstance(value, dict):
        return {k: tagged(v) for k, v in sorted(value.items())}
    if isinstance(value, np.ndarray):
        return ("array", str(value.dtype), value.shape, value.tobytes())
    if isinstance(value, list):
        return ("list", [tagged(v) for v in value])
    return (type(value).__name__, value)


def upgraded(src, tmp_path):
    dst = str(tmp_path / ("v1_" + Path(src).name))
    before = digest(src)
    report = lib.upgrade(str(src), dst)
    assert digest(src) == before            # never changes the source
    return dst, report


# ------------------------------------------------- the real files

@pytest.mark.parametrize("src", EXAMPLES, ids=lambda p: p.name)
def test_the_worked_examples_upgrade(src, tmp_path):
    dst, report = upgraded(src, tmp_path)
    assert report.errors == [], report
    assert lib.validate(dst).errors == []


@pytest.mark.parametrize("case", clean_corpus_cases())
def test_the_clean_corpus_upgrades_or_is_refused_by_name(case, tmp_path):
    dst, report = upgraded(CORPUS / case / "case.mes", tmp_path)
    reason = REFUSED.get(case)
    if reason is None:
        assert report.errors == [], report
        found = lib.validate(dst)
        assert found.errors == [], found
        assert "W12" not in found.warning_ids     # rechunked
        with lib.read(dst) as ds:
            assert all(s.varies == "row" for s in ds.scalars.values())
        return
    assert not os.path.exists(dst)
    assert report.errors
    message = report.errors[0].rule + " " + report.errors[0].message
    assert reason in message, message


@pytest.mark.parametrize("src", FAMILIES, ids=lambda p: p.name)
def test_topolink_families_upgrade(src, tmp_path):
    if not src.exists():
        pytest.skip("not on this machine: %s" % src)
    dst, report = upgraded(src, tmp_path)
    assert report.errors == [], report
    assert lib.validate(dst).errors == []
    with _v0.read(str(src)) as old, lib.read(dst) as new:
        assert new.row_count == old.n_rows
        assert new.kind == "mesh"
        # Node and cell labels of one name sit in different groups.
        for name in ("logical_i", "logical_j", "cad_face_id"):
            assert name in new.mesh.node_arrays
            assert name in new.mesh.cell_arrays
            for group in ("node_arrays", "cell_arrays"):
                np.testing.assert_array_equal(
                    getattr(new.mesh, group)[name].read().values,
                    getattr(old.supports["s0"], group)[name].read().values)
        np.testing.assert_array_equal(
            new.mesh.coordinates.read(rows=[0]).values,
            old.supports["s0"].coordinates.read(slice(0, 1)).values)
        assert new.mesh.support_id == old.supports["s0"].support_id
        assert list(new.labels["member"].names().values) == list(
            old.keys["member"].values.values)
        assert dict(new.notes).keys() == dict(old.notes).keys()
        assert "private" in new._opaque


def test_the_upgraded_capsule_is_one_row_per_member(tmp_path):
    src = FAMILIES[0]
    if not src.exists():
        pytest.skip("not on this machine: %s" % src)
    xr = pytest.importorskip("xarray")
    assert_this_package()
    dst, report = upgraded(src, tmp_path)
    assert report.errors == []
    with lib.read(dst) as ds:
        members = list(ds.labels["member"].names().values)
    with xr.open_dataset(dst) as opened:
        frame = opened.to_dataframe()
    assert len(frame) == len(members) == len(set(members))
    assert [m.decode() if isinstance(m, bytes) else m
            for m in frame["member"]] == members


@pytest.mark.parametrize("src", romlib_files(), ids=lambda p: p.name)
def test_romlib_artifacts_upgrade_with_their_dictionaries_unchanged(
        src, tmp_path):
    dst, report = upgraded(src, tmp_path)
    assert report.errors == [], report
    assert lib.validate(dst).errors == []
    with h5py.File(src, "r") as f, h5py.File(dst, "r") as g:
        ids = sorted(f["callables"]) if "callables" in f else []
        assert ids == (sorted(g["callables"]) if "callables" in g else [])
        for name in ids:
            before = decode_dict(f["callables"][name], reserved=RESERVED_V0)
            after = decode_dict(g["callables"][name], reserved=RESERVED)
            assert tagged(before) == tagged(after)
            assert g["callables"][name].attrs["type"] == \
                f["callables"][name].attrs["type"]
            assert "inputs" not in g["callables"][name].attrs
    with _v0.read(str(src)) as old, lib.read(dst) as new:
        for name, slot in old.scalars.items():
            moved = new.scalars[name]
            assert moved.served == slot.is_callable
            assert moved.callable_id == slot.callable_id
            assert moved.output == slot.output
            if slot.statistic == "band":
                assert (moved.statistic, moved.of) == ("band", slot.of)


# --------------------------------------------- each line and refusal

def v0_dataset():
    ds = _v0.Dataset(writer="v0 tests", created="2026-10-16T00:00:00Z")
    ds.add_category_table("member", ["a", "b"])
    ds.add_key("member", [0, 1, 1], role="group", category="member")
    ds.set_generalisation_group("member")
    ds.add_key("t", [0.0, 0.0, 1.0], role="time", units="s",
               trajectory_group="member")
    ds.add_scalar("cl", [0.1, 0.2, 0.3], units="1")
    return ds


def write_v0(ds, tmp_path, name="v0.mes", check=True):
    path = str(tmp_path / name)
    _v0.write(ds, path, check=check)
    return path


def test_a_time_key_s_trajectory_group_becomes_run_group(tmp_path):
    dst, report = upgraded(write_v0(v0_dataset(), tmp_path), tmp_path)
    assert report.errors == []
    with lib.read(dst) as ds:
        assert ds.parameters["t"].run_group == "member"
        assert ds.parameters["t"].role == "time"
        assert ds.labels["member"].role == "group"
        assert ds.generalisation_group == "member"
        assert ds.scalars["cl"].varies == "row"
    assert [f.message for f in report.warnings if f.rule == ""] == [
        "dropped the root attribute aligned: version 1 has one mesh, so "
        "every row is on it"]


def test_what_version_1_does_not_keep_is_dropped_with_a_line(tmp_path):
    ds = v0_dataset()
    ds.add_category_table("member_of", ["x"])
    ds.add_key("parent_group", [0, 0, 0], role="group",
               category="member_of", parent="member")
    ds.add_scalar("cl_value", [0.1, 0.2, 0.3], units="1",
                  statistic="value")
    s = ds.add_support("s0", coordinates=np.zeros((3, 3)),
                       cells=([5], [0, 3], [0, 1, 2]))
    s.add_node_array("w", np.ones(3), units="m2", dims=("node",),
                     role="weight", recomputed=True)
    s.add_node_array("n", np.ones((3, 3)), dims=("node", "component"),
                     role="normal", recomputed=True)
    dst, report = upgraded(write_v0(ds, tmp_path), tmp_path)
    assert report.errors == [], report
    lines = sorted((f.path, f.message.split(":")[0]) for f in
                   report.warnings if f.rule == "")
    assert lines == [
        ("", "dropped the root attribute aligned"),
        ("labels/parent_group", "dropped parent = member"),
        ("mesh/node_arrays/n", "a normal is now a field with units 1"),
        ("mesh/node_arrays/n", "dropped recomputed, which version 1 does "
                               "not have"),
        ("mesh/node_arrays/w", "dropped this weight array"),
        ("scalars/cl_value", "dropped statistic = value"),
    ]
    with lib.read(dst) as new:
        assert "w" not in new.mesh.node_arrays
        normal = new.mesh.node_arrays["n"]
        assert (normal.role, normal.units, normal.components) == (
            "field", "1", 3)
        assert new.scalars["cl_value"].statistic is None


@pytest.mark.parametrize("key, scalar", [("cl", "cl"), ("mesh", "cd"),
                                         ("t2", "group_x"),
                                         ("coordinates", "cd")])
def test_a_name_that_clashes_in_the_root_is_refused(tmp_path, key, scalar):
    ds = _v0.Dataset(writer="v0 tests", created="2026-10-16T00:00:00Z")
    ds.add_key(key, [0.0, 1.0], role="design", units="1")
    ds.add_scalar(scalar, [0.1, 0.2], units="1")
    dst, report = upgraded(write_v0(ds, tmp_path), tmp_path)
    assert not os.path.exists(dst)
    assert report.error_ids == ["E33"]
    assert len(report.errors) == 1           # one line naming the clash
    assert report.errors[0].path in (key, scalar)


def test_a_dictionary_using_inputs_at_its_top_level_is_refused(tmp_path):
    ds = _v0.Dataset(writer="v0 tests", created="2026-10-16T00:00:00Z")
    ds.add_key("mach", [], role="condition", units="1", lower=0.1,
               upper=0.9)

    class Odd(_v0.Callable):
        type = "odd"

        def __call__(self, keys):
            return {}

        def to_dict(self):
            return {"inputs": "mach", "w": [1.0]}

        @classmethod
        def from_dict(cls, d):
            return cls()

    ds.add_callable("m1", Odd())
    ds.add_callable_slot("cl", units="1", callable="m1", output="cl")
    dst, report = upgraded(write_v0(ds, tmp_path), tmp_path)
    assert report.error_ids == ["E32"]
    assert not os.path.exists(dst)


def test_an_already_upgraded_file_is_refused(tmp_path):
    dst, report = upgraded(write_v0(v0_dataset(), tmp_path), tmp_path)
    again = str(tmp_path / "again.mes")
    second = lib.upgrade(dst, again)
    assert second.error_ids == ["E01"]
    assert "already version 1" in second.errors[0].message
    assert not os.path.exists(again)


def test_a_file_that_is_not_hdf5_is_refused(tmp_path):
    path = tmp_path / "text.mes"
    path.write_text("not a file of this format")
    report = lib.upgrade(str(path), str(tmp_path / "out.mes"))
    assert report.error_ids == ["E01"]


def test_a_version_0_file_with_errors_is_refused(tmp_path):
    ds = v0_dataset()
    path = write_v0(ds, tmp_path)
    with h5py.File(path, "r+") as f:
        del f["scalars/cl"].attrs["units"]
    dst, report = upgraded(path, tmp_path)
    assert report.error_ids == ["E11"]
    assert "version 0 file breaks" in report.errors[0].message
    assert not os.path.exists(dst)


def test_upgrade_never_creates_constants(tmp_path):
    ds = _v0.Dataset(writer="v0 tests", created="2026-10-16T00:00:00Z")
    ds.add_key("x", [1.0, 2.0, 3.0], role="design", units="m")
    ds.add_scalar("s_ref", [4.0, 4.0, 4.0], units="m2")
    dst, report = upgraded(write_v0(ds, tmp_path), tmp_path)
    assert report.errors == []
    with lib.read(dst) as new:
        assert new.scalars["s_ref"].varies == "row"
        np.testing.assert_array_equal(new.scalars["s_ref"].read(),
                                      [4.0, 4.0, 4.0])


def test_an_upgraded_axis_is_points(tmp_path):
    ds = _v0.Dataset(writer="v0 tests", created="2026-10-16T00:00:00Z")
    ds.add_key("x", [1.0, 2.0], role="design", units="m")
    s = ds.add_support("s0", kind="axis", coordinates=[0.0, 0.5, 1.0],
                       units="Hz")
    s.add_node_array("spl", np.ones((2, 3)), units="dB", dims=("row",
                                                                "node"))
    src = write_v0(ds, tmp_path)
    dst, report = upgraded(src, tmp_path)
    assert report.errors == []
    with lib.read(dst) as new, _v0.read(src) as old:
        assert new.kind == "points"
        assert new.mesh.support_id == old.supports["s0"].support_id
        assert new.mesh.coordinates.read().shape == (3, 1)

"""Version 1 files made hostile: links, depth, sizes.

The version 0 hostile corpus is version 0 files, which a version 1
reader refuses at E01 before it looks further. These are version 1
files with the same kinds of damage, so that the version 1 reader and
validator are held to the same contract: findings or a MestraError
naming a rule, never another exception, and no unbounded allocation.
"""

from __future__ import annotations

import shutil

import h5py
import numpy as np
import pytest

from mestra import limits
from tests.v1_cases import lib, write_case


@pytest.fixture
def family(tmp_path):
    (tmp_path / "base").mkdir()
    path = str(tmp_path / "hostile.mes")
    shutil.copy(write_case("family", tmp_path / "base"), path)
    return path


def test_a_soft_link_in_the_root_is_never_followed(family):
    with h5py.File(family, "r+") as f:
        f["loop"] = h5py.SoftLink("/loop")
        f["alias"] = h5py.SoftLink("/mach")
    report = lib.validate(family)
    assert sorted(x.path for x in report.errors if x.rule == "E40") == [
        "alias", "loop"]
    with pytest.raises(lib.MestraError) as caught:
        lib.read(family)
    assert caught.value.rule == "E40"
    with lib.read(family, strict=False) as ds:
        assert [p.rule for p in ds._problems] == ["E40", "E40"]


def test_an_external_link_in_the_mesh_is_never_followed(family):
    with h5py.File(family, "r+") as f:
        f["mesh/node_arrays/elsewhere"] = h5py.ExternalLink(
            "/etc/passwd", "/x")
    report = lib.validate(family)
    assert [x.path for x in report.errors if x.rule == "E40"] == [
        "mesh/node_arrays/elsewhere"]
    with lib.read(family, strict=False) as ds:
        assert ds._lossy == ["mesh/node_arrays/elsewhere"]
        with pytest.raises(lib.MestraError) as caught:
            lib.write(ds, family + ".copy.mes")
        assert caught.value.rule == "E41"


def test_a_dictionary_deeper_than_the_cap(family, tmp_path):
    model = write_case("model", tmp_path)
    with h5py.File(model, "r+") as f:
        group = f["callables/m1"]
        for _ in range(limits.MAX_DEPTH + 5):
            group = group.create_group("d")
    report = lib.validate(model)
    assert "E41" in report.error_ids
    with pytest.raises(lib.MestraError) as caught:
        lib.read(model)                       # an open sees the depth
    assert caught.value.rule == "E41"
    with lib.read(model, strict=False) as ds:
        assert ds.callables["m1"].type == "affine"
        assert any(p.rule == "E41" for p in ds._problems)


def test_a_huge_declared_parameter_is_not_allocated(family):
    with h5py.File(family, "r+") as f:
        old = f["mach"]
        attrs = {k: old.attrs[k] for k in old.attrs
                 if k not in ("DIMENSION_LIST",)}
        old.dims[0].detach_scale(f["row"])
        del f["mach"]
        huge = f.create_dataset("mach", shape=(1 << 40,), dtype="<f8",
                                chunks=(1 << 15,), maxshape=(None,))
        for key, value in attrs.items():
            huge.attrs[key] = value
        huge.dims[0].attach_scale(f["row"])
    report = lib.validate(family)
    assert "E16" in report.error_ids
    with pytest.raises(lib.MestraError) as caught:
        lib.read(family)
    assert caught.value.rule in ("E16", "E19")
    with lib.read(family, strict=False) as ds:
        with pytest.raises(lib.MestraError) as caught:
            ds.parameters["mach"].values()
        assert caught.value.rule == "E41"
        assert ds.parameters["mach"].values([0, 1]).shape == (2,)


def test_member_kinds_the_format_does_not_expect(family):
    with h5py.File(family, "r+") as f:
        del f["mesh/node_arrays/face"]
        f["mesh/node_arrays"].create_group("face")
        f.create_group("categories/oops")
    report = lib.validate(family)
    assert report.errors, report
    with lib.read(family, strict=False) as ds:
        assert "oops" not in ds.categories
        assert any(p.path == "categories/oops" for p in ds._problems)


def test_unknown_groups_are_kept_and_not_walked(family):
    with h5py.File(family, "r+") as f:
        group = f.create_group("vendor")
        for _ in range(limits.MAX_DEPTH + 10):
            group = group.create_group("g")
        group.attrs["note"] = np.int32(3)
    report = lib.validate(family)
    assert report.errors == []
    assert [x.path for x in report.warnings if x.rule == "W11"] == [
        "vendor"]

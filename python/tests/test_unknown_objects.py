"""What this version does not know, and which rule covers it.

The case is an ordinary contiguous dataset named `row` inside a
support group, attached to the file's `row` scale. It can be read
as E27, as E27 with W11, or as nothing at all, so whether an unknown
dataset inside a known group is checked is worth stating plainly.
The text already does, in two steps.

Section 14 exempts two things by name from the byte-level rules of
sections 18 to 25: "`/private` is not checked, and neither is any
group this version of the format does not know, which is reported as
W11 and otherwise left alone". A dataset inside a support group is
neither of those, so it is one of the "public objects only" the rules
are checked on: it carries a row dimension, it is not chunked, and
that is E27.

Section 28 is the second step, and it is why there is nothing to make
room for: what a version may add is "new optional attributes" and
"new optional groups ... at the root and inside a support". Datasets
are not on that list, so an unknown dataset is not a
forward-compatibility extension point and is not something a later
version could have meant. It draws no W11 either, because W11 is "an
attribute or a group this reader does not know" and a dataset is
neither.

The three cases are pinned together here, because the argument is
about which of them a thing is and not about any one of them alone.
"""

from __future__ import annotations

import shutil

import h5py
import numpy as np

from mestra import _v0 as mestra
from tests import corpus


def _case(tmp_path, name: str) -> str:
    path = str(tmp_path / (name + ".mes"))
    shutil.copy(corpus.case_path("mesh_two_rows"), path)
    return path


def test_an_unknown_dataset_in_a_support_is_checked_like_any_other(
        tmp_path):
    """E27 and nothing else. Section 14 checks the byte-level rules
    on every public object that is not `/private` and not a group
    this version does not know."""
    path = _case(tmp_path, "stray_dataset")
    with h5py.File(path, "r+") as f:
        stray = f["/supports/s0"].create_dataset(
            "row", data=np.array([1.0, 2.0]), dtype="<f8",
            track_times=False)
        stray.dims[0].attach_scale(f["row"])
    report = mestra.validate(path)
    assert report.error_ids == ["E27"]
    assert [f.where for f in report.errors] == ["/supports/s0/row"]
    # Not W11: that rule is "an attribute or a group this reader does
    # not know", and section 28 adds groups and attributes, never
    # datasets.
    assert report.warning_ids == []


def test_the_same_dataset_chunked_breaks_nothing(tmp_path):
    """The rule is E27 and not "an unknown dataset". Chunked, the
    same stray dataset is a public object breaking no byte-level
    rule, and the file is accepted."""
    path = _case(tmp_path, "stray_chunked")
    with h5py.File(path, "r+") as f:
        stray = f["/supports/s0"].create_dataset(
            "row", data=np.array([1.0, 2.0]), dtype="<f8",
            maxshape=(None,), chunks=(2,), track_times=False)
        stray.dims[0].attach_scale(f["row"])
    report = mestra.validate(path)
    assert report.error_ids == []
    assert report.warning_ids == []


def test_an_unknown_group_in_a_support_is_left_alone(tmp_path):
    """The other side of the same sentence: a group this version
    does not know is W11 and otherwise not checked, so the same
    unchunked dataset inside one draws nothing."""
    path = _case(tmp_path, "stray_group")
    with h5py.File(path, "r+") as f:
        inside = f["/supports/s0"].create_group("fitted")
        stray = inside.create_dataset(
            "row", data=np.array([1.0, 2.0]), dtype="<f8",
            track_times=False)
        stray.dims[0].attach_scale(f["row"])
    report = mestra.validate(path)
    assert report.error_ids == []
    assert report.warning_ids == ["W11"]
    assert [f.where for f in report.warnings] == ["/supports/s0/fitted"]

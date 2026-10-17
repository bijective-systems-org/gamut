"""The public surface is pinned: docs/surface/python.json is what
`tests/surface.py` generates from `mestra.__all__`, and a change to
either is a reviewed change to the file. Regenerate with
`python -m tests.surface` from python/."""

from __future__ import annotations

import json

import pytest

from tests import surface
from tests.v1_cases import lib

#: Version 0 names that are not public in version 1.
RETIRED = ("add_key", "add_callable_slot", "set_callable_coordinates",
           "set_row_support", "add_support", "Key", "ScalarSlot",
           "ArraySlot", "Support", "Storage", "CategoryTable",
           "keys_table", "callable_from_dict", "compute_weights",
           "support_digest", "support_ids", "encode_dict", "decode_dict",
           "keys_of_role", "arrays", "is_callable", "slots")


def committed():
    return json.loads(surface.SURFACE.read_text(encoding="utf-8"))


def test_the_committed_surface_is_the_generated_one():
    assert surface.text() == surface.SURFACE.read_text(encoding="utf-8"), (
        "the public surface changed; review it, then run "
        "`python -m tests.surface` from python/")


def test_a_rename_changes_the_surface(monkeypatch):
    monkeypatch.setattr(lib.Dataset, "as_xarray", lib.Dataset.to_xarray,
                        raising=False)
    monkeypatch.delattr(lib.Dataset, "to_xarray")
    assert surface.generate() != committed()


def test_a_new_argument_changes_the_surface(monkeypatch):
    original = lib.read

    def read(path, lazy=True, strict=True, cache=None):
        return original(path, lazy, strict)

    monkeypatch.setattr(lib, "read", read)
    assert surface.generate() != committed()


def test_no_version_0_name_is_public():
    pinned = committed()["names"]
    members = {m for entry in pinned.values()
               for m in entry.get("members", {})}
    for name in RETIRED:
        assert name not in pinned and name not in members, name
        assert not hasattr(lib, name), name


def test_nothing_private_is_pinned():
    for name, entry in committed()["names"].items():
        assert not name.startswith("_") or name == "__version__"
        for member in entry.get("members", {}):
            assert not member.startswith("_"), (name, member)


@pytest.mark.parametrize("name", ["Dataset", "Slot", "Mesh", "Parameter",
                                  "Label"])
def test_no_member_hands_out_an_internal_type(name):
    """Values come back as arrays with named dimensions, strings and
    numbers, never as the sources that hold them."""
    for member in committed()["names"][name]["members"]:
        assert member not in ("data", "extra", "opaque", "unknown",
                              "present", "lossy", "problems",
                              "callable_inputs")

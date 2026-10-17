"""What writing and opening promise, beyond the layout.

A write is staged and published only when the staged file validates,
so a refusal leaves an existing destination as it was; a destination
that cannot take a file is refused before anything is made; an
existing file keeps its permission bits; the same dataset gives the
same bytes twice; values a lazy dataset still holds are copied a block
at a time. Opening reads no slot values and no dictionary, and the
open, the read and the validator name the same rule for a file they
refuse.
"""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

import h5py
import numpy as np
import pytest

from mestra import model, writer
from mestra.encoding import write_string_attr
from tests.test_v1_rules import recreate
from tests.v1_cases import CASES, content, lib, write_case


def test_a_refused_write_leaves_the_destination_as_it_was(tmp_path):
    path = str(tmp_path / "out.mes")
    lib.write(CASES["table"](), path)
    before = Path(path).read_bytes()
    bad = CASES["table"]()
    bad.scalars["cl"].units = "m per"           # E11, decided on the file
    with pytest.raises(lib.MestraError) as caught:
        lib.write(bad, path)
    assert caught.value.rule == "E11"
    assert Path(path).read_bytes() == before
    assert sorted(os.listdir(tmp_path)) == ["out.mes"]   # nothing staged


@pytest.mark.parametrize("where", ["missing/dir/out.mes", "."])
def test_a_destination_that_cannot_take_a_file(tmp_path, where):
    with pytest.raises(lib.MestraError) as caught:
        lib.write(CASES["table"](), str(tmp_path / where))
    assert caught.value.rule == ""


def test_an_existing_file_keeps_its_permission_bits(tmp_path):
    path = str(tmp_path / "out.mes")
    lib.write(CASES["table"](), path)
    os.chmod(path, 0o640)
    lib.write(CASES["table"](), path)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o640


@pytest.mark.parametrize("name", list(CASES))
def test_the_same_dataset_gives_the_same_bytes(tmp_path, name):
    one, two = str(tmp_path / "one.mes"), str(tmp_path / "two.mes")
    lib.write(CASES[name](), one)
    lib.write(CASES[name](), two)
    assert Path(one).read_bytes() == Path(two).read_bytes()


def test_lazy_values_are_copied_a_block_at_a_time(tmp_path, monkeypatch):
    ds = lib.Dataset(created="2026-10-16T00:00:00Z")
    ds.add_parameter("x", np.arange(200.0), "design", "1")
    mesh = ds.set_mesh(coordinates=np.zeros((400, 1)), units="m",
                       dims=("node", "component"))
    mesh.add_node_array("p", np.arange(200 * 400.0).reshape(200, 400),
                        "Pa", ("row", "node"))
    path = str(tmp_path / "big.mes")
    lib.write(ds, path)
    reads = []
    original = model.FileSource.read

    def counting(self, lead=None, sites=None):
        reads.append((self.path, lead))
        return original(self, lead, sites)

    monkeypatch.setattr(model.FileSource, "read", counting)
    monkeypatch.setattr(writer, "_BLOCK_BYTES", 400 * 8 * 7)
    again = str(tmp_path / "again.mes")
    with lib.read(path) as lazy:
        lib.write(lazy, again)
    blocks = [lead for p, lead in reads if p == "/mesh/node_arrays/p"]
    assert len(blocks) > 1 and all(isinstance(b, slice) for b in blocks)
    assert content(again) == content(path)


def test_an_open_reads_no_values(tmp_path, monkeypatch):
    path = write_case("model", tmp_path)
    family = write_case("family", tmp_path)
    reads = []
    monkeypatch.setattr(model.FileSource, "read",
                        lambda self, *a, **k: reads.append(self.path))
    with lib.read(family) as ds:
        _ = (ds.kind, ds.addons, ds.row_count, list(ds.parameters),
             list(ds.labels), ds.mesh.support_id,
             [s.dims for s in ds.mesh.node_arrays.values()])
    with lib.read(path) as ds:
        assert list(ds.callables) == ["m1"]
        assert "m1" in ds.callables._pending       # dictionary not read
    assert reads == []


@pytest.mark.parametrize("change, rule", [
    ("filter", "E29"), ("served dataset", "E30"), ("attribute", "E19"),
    ("not utf-8", "E26"), ("length", "E16"), ("soft link", "E40")])
def test_open_read_and_validate_name_the_same_rule(tmp_path, change, rule):
    path = str(tmp_path / "f.mes")
    shutil.copy(write_case("family", tmp_path), path)
    with h5py.File(path, "r+") as f:
        if change == "filter":
            recreate(f, "cl", fletcher32=True)
        elif change == "served dataset":
            write_string_attr(f["cl"], "source", "callable:m9")
        elif change == "attribute":
            f["mach"].attrs["lower"] = np.float32(0.5)
        elif change == "not utf-8":
            f["mesh"].attrs.create("kind", b"me\xffsh",
                                   dtype=h5py.string_dtype("utf-8", 6))
        elif change == "length":
            f["cl"].resize((5,))
        else:
            f["alias"] = h5py.SoftLink("/cl")
    assert rule in lib.validate(path).error_ids
    with pytest.raises(lib.MestraError) as caught:
        lib.read(path)
    assert caught.value.rule == rule
    with pytest.raises(lib.MestraError) as caught:
        lib.read(path, lazy=False)
    assert caught.value.rule == rule

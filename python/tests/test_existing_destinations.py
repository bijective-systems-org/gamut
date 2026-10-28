"""Creating output must never truncate or delete a destination it did not own."""
import json
import os

import numpy as np
import pytest

import gamut
from gamut import cli


@pytest.mark.parametrize("parameters", [{"x": "1"}, {"x": {"role": "condition"}}])
def test_create_preserves_existing_destination_on_any_declaration(tmp_path, parameters):
    target = tmp_path / "study.gamut"
    original = b"existing study bytes must survive"
    target.write_bytes(original)
    with pytest.raises(gamut.GamutError):
        with gamut.create(str(target), writer="test", parameters=parameters):
            pass
    assert target.read_bytes() == original


@pytest.mark.parametrize("link", ["symlink", "hardlink"])
def test_create_preserves_link_target(tmp_path, link):
    original = tmp_path / "original.gamut"
    original.write_bytes(b"original bytes")
    target = tmp_path / "output.gamut"
    if link == "symlink":
        try:
            target.symlink_to(original)
        except OSError:
            pytest.skip("symbolic links unavailable")
    else:
        try:
            os.link(original, target)
        except OSError:
            pytest.skip("hard links unavailable")
    with pytest.raises(gamut.GamutError):
        gamut.create(str(target), writer="test")
    assert original.read_bytes() == b"original bytes"
    assert target.read_bytes() == b"original bytes"


@pytest.mark.parametrize("failure", ["bad_units", "bad_run", "bad_mesh"])
def test_build_preserves_existing_destination(tmp_path, capsys, failure):
    target = tmp_path / "study.gamut"
    target.write_bytes(b"keep previous study")
    (tmp_path / "runs.csv").write_text("x\nnot-a-number\n" if failure == "bad_run" else "x\n1\n")
    doc = {"writer": "test", "parameters": {"x": "1"}, "runs": "runs.csv"}
    if failure == "bad_units":
        doc["parameters"] = {"x": {"role": "condition"}}
    if failure == "bad_mesh":
        doc["mesh"] = {"kind": "invalid", "per": "fixed", "units": "m", "file": "mesh.npz"}
        np.savez(tmp_path / "mesh.npz", points=np.zeros((1, 3)))
    document = tmp_path / "doc.json"
    document.write_text(json.dumps(doc))
    assert cli.main(["build", str(document), "-o", str(target), "--json"]) != 0
    capsys.readouterr()
    assert target.read_bytes() == b"keep previous study"


def test_failed_fresh_build_leaves_no_output(tmp_path, capsys):
    target = tmp_path / "new.gamut"
    (tmp_path / "runs.csv").write_text("x\nnot-a-number\n")
    document = tmp_path / "doc.json"
    document.write_text(json.dumps({"writer": "test", "parameters": {"x": "1"}, "runs": "runs.csv"}))
    assert cli.main(["build", str(document), "-o", str(target), "--json"]) != 0
    capsys.readouterr()
    assert not target.exists()


def test_existing_valid_study_keeps_its_runs_on_refusal(tmp_path):
    target = tmp_path / "runs.gamut"
    with gamut.create(str(target), writer="old", parameters={"x": "1"}) as study:
        study.add_runs({"x": [1., 2., 3.]})
    original = target.read_bytes()
    with pytest.raises(gamut.GamutError):
        gamut.create(str(target), writer="new", parameters={"x": {"role": "condition"}})
    assert target.read_bytes() == original
    with gamut.open(str(target)) as study:
        np.testing.assert_array_equal(study.get_parameter("x"), [1., 2., 3.])


@pytest.mark.parametrize("operation", ["copy", "extract", "evaluate", "create_model"])
def test_other_creating_operations_preserve_existing_destination(tmp_path, operation):
    source = tmp_path / "source.gamut"
    with gamut.create(str(source), writer="test", parameters={"x": "1"}) as study:
        study.add_runs({"x": [0., 1.]})
    model = tmp_path / "model.gamut"
    with gamut.create_model(str(model), writer="test",
                            parameters={"x": {"units": "1", "lower": 0, "upper": 1}},
                            scalars={"y": {"units": "1", "model": "fit", "output": "y"}}) as study:
        study.add_model("fit", gamut.Nearest(["x"], [0.], [1.], [[0.], [1.]], {"y": [0., 2.]}), ["x"])
    target = tmp_path / "destination.gamut"
    target.write_bytes(b"keep existing destination")
    with pytest.raises(gamut.GamutError):
        if operation == "copy":
            gamut.write_copy(str(source), str(target))
        elif operation == "extract":
            gamut.extract(str(source), str(target), [0])
        elif operation == "evaluate":
            gamut.evaluate(str(model), {"x": [.5]}, path=str(target))
        else:
            gamut.create_model(str(target), writer="test")
    assert target.read_bytes() == b"keep existing destination"

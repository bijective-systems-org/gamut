"""The command line, used the way an agent uses it: write a document and
files, build, inspect with --json, extract data to files."""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys

import numpy as np

import gamut
from gamut import cli


def run(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def make_inputs(tmp_path, n_runs=4):
    xs, ys = np.meshgrid(np.arange(3.0), np.arange(2.0))
    pts = np.stack([xs.ravel(), ys.ravel(), np.zeros(6)], axis=1)
    np.savez(tmp_path / "mesh.npz", points=pts, types=np.array([9, 9], np.uint8),
             offsets=np.array([0, 4, 8]), connectivity=np.array([0, 1, 4, 3, 1, 2, 5, 4]),
             zone=np.array([0, 1]))
    rows = []
    for i in range(n_runs):
        np.save(tmp_path / f"p_{i}.npy", np.full(6, float(i)))
        rows.append({"mach": 0.3 + 0.1 * i, "alpha": float(i), "status": "converged" if i else "failed",
                     "cl": 0.1 * i, "cd": 0.01, "p": f"p_{i}.npy"})
    with open(tmp_path / "runs.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def test_build_info_validate_get(tmp_path, capsys):
    code, out, err = run(capsys, "build", "--example")
    assert code == 0
    doc = json.loads(out)
    assert "runs.csv" in doc["runs"] and "mesh.npz" in err
    make_inputs(tmp_path)
    doc["portion_marking"] = "Example marking"
    (tmp_path / "doc.json").write_text(json.dumps(doc))
    target = str(tmp_path / "study.gamut")
    code, out, _ = run(capsys, "build", str(tmp_path / "doc.json"), "-o", target, "--json")
    assert code == 0, out
    assert json.loads(out) == {"wrote": target, "rows": 4}

    code, out, _ = run(capsys, "info", target, "--json")
    info = json.loads(out)
    assert info["type"] == "shared" and info["row_count"] == 4
    assert info["metadata"]["portion_marking"] == "Example marking"
    assert info["mesh"]["nodes"] == 6 and info["mesh"]["cells"] == 2
    assert [p["name"] for p in info["parameters"]] == ["alpha", "mach"]
    assert info["labels"][0]["counts"] == {"converged": 3, "failed": 1}
    code, text, _ = run(capsys, "info", target)
    assert "shared mesh, 4 runs" in text and "p [Pa] at nodes" in text
    assert "  marking     Example marking" in text

    code, out, _ = run(capsys, "validate", target, "--json")
    v = json.loads(out)
    assert code == 0 and v["errors"] == 0 and [f["rule"] for f in v["findings"]] == ["W2"]

    csv_out = str(tmp_path / "cl.csv")
    code, out, _ = run(capsys, "get", target, "mach", "cl", "status", "--where",
                       "status == converged and mach > 0.35", "-o", csv_out, "--json")
    got = json.loads(out)
    assert got["rows"] == 3 and got["units"]["cl"] == "1"    # mach 0.4, 0.5, 0.6
    lines = open(csv_out).read().splitlines()
    assert lines[0] == "row,mach,cl,status" and lines[1].startswith("1,")
    npz = str(tmp_path / "p.npz")
    code, out, _ = run(capsys, "get", target, "p", "--rows", "1:3", "-o", npz, "--json")
    assert code == 0
    z = np.load(npz)
    assert z["p"].shape == (2, 6) and z["row"].tolist() == [1, 2]
    # A zone of cells cannot select the nodes of a node field.
    code, out, _ = run(capsys, "get", target, "p", "--zone", "zone=inlet", "-o", npz, "--json")
    assert code == 2 and "at nodes" in json.loads(out)["problems"][0]["message"]   # the arguments'


def test_vtk_command_without_its_extra_says_what_to_install():
    # A fresh interpreter, so no other test has imported pandas already.
    code = ("import sys; sys.modules['pandas'] = None; from gamut.cli import vtk_main; "
            "raise SystemExit(vtk_main(['--help']))")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 2, result.stderr
    assert 'pip install "bijective-gamut[vtk]"' in result.stderr
    assert "Traceback" not in result.stderr


def _zoned(path):
    import gamut
    xs, ys = np.meshgrid(np.arange(3.0), np.arange(2.0))
    pts = np.stack([xs.ravel(), ys.ravel()], axis=1)
    cells = (np.array([9, 9], np.uint8), np.array([0, 4, 8]), np.array([0, 1, 4, 3, 1, 2, 5, 4]))
    with gamut.create(path, writer="t", mesh="shared", per="fixed", coordinates={"units": "m", "axes": 2},
                      parameters={"x": "1"}, fields={"q": {"units": "1", "at": "cell"}},
                      mesh_labels={"zone": {"at": "cell", "categories": ["a", "b"]}}) as s:
        s.set_mesh(pts, cells, labels={"zone": np.array([0, 1])})
        s.add_runs({"x": [1.0, 2.0, 3.0]}, fields={"q": np.ones((3, 2))})


def test_malformed_input_is_reported_with_the_guides_exit_status(tmp_path, capsys):
    m = str(tmp_path / "m.gamut")
    _zoned(m)
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    code, _, err = run(capsys, "build", str(bad), "-o", str(tmp_path / "x.gamut"))
    assert code == 1 and err.startswith("error: ") and "is not JSON at line 1" in err
    for argv, says in ((["--zone", "zone=c"], "'c' is not a name in zone's table (a, b)"),
                       (["--zone", "zone"], "--zone takes LABEL=NAME"),
                       (["--rows", "7"], "--rows: "),
                       (["--rows", "-1"], "--rows: ")):
        for out in ("z.csv", "z.gamut"):
            if out == "z.gamut" and argv[0] == "--zone":
                continue
            names = [] if out == "z.gamut" else ["q"]
            code, _, err = run(capsys, "get", m, *names, *argv, "-o", str(tmp_path / out))
            assert code == 2 and err.startswith("error: ") and says in err, (argv, out, err)
    code, _, _ = run(capsys, "get", m, "q", "--zone", "zone=b", "-o", str(tmp_path / "b.csv"))
    assert code == 0


def test_rows_are_checked_without_reading_every_row_and_file_faults_stay_exit_1(tmp_path, capsys):
    m = str(tmp_path / "m.gamut")
    _zoned(m)
    code, _, _ = run(capsys, "get", m, "x", "--rows", "1", "-o", str(tmp_path / "x.npy"))
    assert code == 0 and np.load(tmp_path / "x.npy").tolist() == [2.0]
    import h5py
    with h5py.File(m, "r") as f:       # a damaged row chunk: a file fault, exit 1
        info = f["row"].id.get_chunk_info(0)
    with open(m, "r+b") as fh:
        fh.seek(info.byte_offset)
        fh.write(b"\xff" * info.size)
    code, _, err = run(capsys, "get", m, "x", "--rows", "0", "-o", str(tmp_path / "y.csv"))
    assert code in (1,) and err.startswith("error: "), err


def test_a_zone_code_that_is_not_a_number_is_a_usage_error(tmp_path, capsys):
    import gamut
    p = str(tmp_path / "c.gamut")
    xs, ys = np.meshgrid(np.arange(3.0), np.arange(2.0))
    pts = np.stack([xs.ravel(), ys.ravel()], axis=1)
    cells = (np.array([9, 9], np.uint8), np.array([0, 4, 8]), np.array([0, 1, 4, 3, 1, 2, 5, 4]))
    with gamut.create(p, writer="t", mesh="shared", per="fixed", coordinates={"units": "m", "axes": 2},
                      parameters={"x": "1"}, fields={"q": {"units": "1", "at": "cell"}},
                      mesh_labels={"zone": {"at": "cell"}}) as s:
        s.set_mesh(pts, cells, labels={"zone": np.array([0, 1])})
        s.add_runs({"x": [1.0]}, fields={"q": np.ones((1, 2))})
    for bad in ("--1", "\u00b2", "1.5"):
        code, out, _ = run(capsys, "get", p, "q", "--zone", f"zone={bad}", "-o",
                           str(tmp_path / "z.csv"), "--json")
        assert code == 2 and json.loads(out)["problems"][0]["message"].startswith("--zone"), (bad, out)


def test_rows_of_a_huge_file_are_checked_without_an_array_of_every_row(tmp_path, capsys):
    import gamut
    import h5py
    p = str(tmp_path / "h.gamut")
    with gamut.create(p, writer="t", parameters={"x": "1"}) as s:
        s.add_runs({"x": [1.0, 2.0]})
    with h5py.File(p, "r+") as f:          # 2**40 rows declared, two stored
        for name in ("row", "x"):
            f[name].resize((1 << 40,))
    code, _, err = run(capsys, "get", p, "x", "--rows", "1", "-o", str(tmp_path / "x.npy"))
    assert code == 0, err
    assert np.load(tmp_path / "x.npy").tolist() == [2.0]


def test_an_existing_export_is_replaced_only_with_force(tmp_path, capsys):
    m = str(tmp_path / "m.gamut")
    _zoned(m)
    out = tmp_path / "x.csv"
    out.write_text("keep me")
    code, _, err = run(capsys, "get", m, "x", "-o", str(out))
    assert code == 2 and "--force" in err and out.read_text() == "keep me"
    code, _, _ = run(capsys, "get", m, "x", "--force", "-o", str(out))
    assert code == 0 and out.read_text() != "keep me"


def test_an_npy_output_named_in_capitals_is_checked_where_numpy_writes(tmp_path, capsys):
    m = str(tmp_path / "m.gamut")
    _zoned(m)
    written = tmp_path / "x.NPY.npy"
    written.write_bytes(b"keep me")
    code, _, err = run(capsys, "get", m, "x", "-o", str(tmp_path / "x.NPY"))
    assert code == 2 and "--force" in err and written.read_bytes() == b"keep me"


def test_every_json_failure_has_one_shape_and_its_exit_status(tmp_path, capsys):
    p = str(tmp_path / "t.gamut")
    with gamut.create(p, writer="t", parameters={"x": "1"}, scalars={"y": "1"}) as s:
        s.add_runs({"x": [1.0, 2.0], "y": [3.0, 4.0]})
    bad_doc = tmp_path / "bad.json"
    bad_doc.write_text(json.dumps({"writer": "t"}))
    null_doc = tmp_path / "null.json"
    null_doc.write_text("null")
    cases = [
        (1, ["info", str(tmp_path / "none.gamut"), "--json"], "there is no file"),
        (1, ["build", str(null_doc), "-o", str(tmp_path / "n.gamut"), "--json"], "not a JSON object"),
        (2, ["get", p, "-o", str(tmp_path / "none.csv"), "--json"], "name what to write"),
        (2, ["get", p, "x", "-o", str(tmp_path / "x.gamut"), "--json"], "keeps every name"),
        (2, ["get", p, "x", "-o", str(tmp_path / "no" / "dir.csv"), "--json"], "No such file"),
        (1, ["build", str(bad_doc), "-o", str(tmp_path / "b.gamut"), "--json"], ""),
        (2, ["get", p, "x", "y", "-o", str(tmp_path / "two.npy"), "--json"], "a .npy holds one array"),
        (2, ["get", p, "x", "-o", str(tmp_path / "x.txt"), "--json"], "OUT ends in"),
        (2, ["get", p, "x", "--json"], "-o/--output"),                       # argparse's own mistake
        (2, ["build", "--json"], "gamut build DOC.json"),
    ]
    for status, argv, says in cases:
        code, out, err = run(capsys, *argv)
        doc = json.loads(out)
        assert code == status, (argv, out, err)
        assert list(doc) == ["problems"] and doc["problems"], (argv, out)
        assert all(set(x) == {"rule", "path", "message"} for x in doc["problems"]), (argv, out)
        assert says in doc["problems"][0]["message"], (argv, out)
    assert not (tmp_path / "two.npy").exists() and not (tmp_path / "x.txt").exists()
    # validate's document is its findings, a file it cannot open among them.
    code, out, _ = run(capsys, "validate", str(tmp_path / "none.gamut"), "--json")
    assert code == 1 and json.loads(out)["findings"][0]["rule"] == "E1"


def test_a_constant_is_refused_for_csv_before_the_output_exists(tmp_path, capsys):
    p = str(tmp_path / "c.gamut")
    with gamut.create(p, writer="t", parameters={"x": "1"}, constants={"area": (2.5, "m2")}) as s:
        s.add_runs({"x": [1.0, 2.0]})
    out = tmp_path / "area.csv"
    out.write_text("kept")
    code, text, _ = run(capsys, "get", p, "area", "-o", str(out), "--force", "--json")
    assert code == 2 and "is a constant" in json.loads(text)["problems"][0]["message"]
    assert out.read_text() == "kept"                          # not truncated before the refusal


def test_a_malformed_document_or_argument_is_reported_not_raised(tmp_path, capsys):
    p = str(tmp_path / "t.gamut")
    with gamut.create(p, writer="t", parameters={"x": "1"}, scalars={"y": "1"}) as s:
        s.add_runs({"x": [1.0, 2.0], "y": [3.0, 4.0]})

    def doc(name, body, csv_text="x,y\n1,2\n"):
        (tmp_path / f"{name}.csv").write_text(csv_text)
        (tmp_path / f"{name}.json").write_text(json.dumps({**body, "runs": f"{name}.csv"}))
        return str(tmp_path / f"{name}.json")

    base = {"writer": "t", "parameters": {"x": "1"}, "scalars": {"y": "1"}}
    cases = [
        (1, doc("list", {**base, "parameters": ["x"]}), "parameters", "is a list"),
        (1, doc("short", base, "x,y\n1\n"), "runs line 2", "fewer cells"),
        (1, doc("long", base, "x,y\n1,2,3\n"), "runs line 2", "more cells"),
        (1, doc("spec", {**base, "parameters": {"x": 5}}), "parameters.x", "give its units"),
        (1, doc("const", {**base, "constants": {"c": 5}}), "constants.c", "[number, units]"),
    ]
    for status, path, key, says in cases:
        code, out, err = run(capsys, "build", path, "-o", str(tmp_path / "o.gamut"), "--json")
        problems = json.loads(out)["problems"]
        assert code == status and any(x["path"] == key and says in x["message"] for x in problems), \
            (path, out, err)
        assert not (tmp_path / "o.gamut").exists()

    code, out, _ = run(capsys, "get", p, "x", "--where", "x >>> 1", "-o", str(tmp_path / "w.csv"), "--json")
    assert code == 2 and json.loads(out)["problems"][0]["message"].startswith("where")
    code, out, _ = run(capsys, "get", p, "-o", p, "--json")      # the input itself
    assert code == 2 and "never replaced" in json.loads(out)["problems"][0]["message"]

    # Any name goes to .npz, row included, as np.savez's own keyword would not.
    code, out, _ = run(capsys, "get", p, "row", "x", "-o", str(tmp_path / "r.npz"), "--json")
    assert code == 0, out
    z = np.load(tmp_path / "r.npz")
    assert z["row"].tolist() == [0, 1] and z["x"].tolist() == [1.0, 2.0]


def test_the_contract_holds_for_odd_documents_files_and_arguments(tmp_path, capsys):
    import h5py
    p = str(tmp_path / "t.gamut")
    with gamut.create(p, writer="t", parameters={"x": "1"}, scalars={"y": "1"}) as s:
        s.add_runs({"x": [1.0, 2.0], "y": [3.0, 4.0]})
    mesh = str(tmp_path / "m.gamut")
    with gamut.create(mesh, writer="t", mesh="shared", per="fixed", coordinates={"units": "m", "axes": 2},
                      parameters={"x": "1"}, fields={"q": {"units": "1", "at": "node"}}) as s:
        s.set_mesh(np.zeros((2, 2)))
        s.add_runs({"x": [1.0]}, fields={"q": np.zeros((1, 2))})
    np.save(tmp_path / "ok.npy", np.zeros(2))
    (tmp_path / "empty.npy").write_bytes(b"")

    def doc(name, body, csv_text="x,y\n1,2\n"):
        (tmp_path / f"{name}.csv").write_text(csv_text)
        (tmp_path / f"{name}.json").write_text(json.dumps({"writer": "t", "parameters": {"x": "1"},
                                                           "scalars": {"y": "1"}, **body,
                                                           "runs": f"{name}.csv"}))
        return str(tmp_path / f"{name}.json")

    documents = [
        doc("meshfile", {"mesh": {"kind": "shared", "per": "fixed", "units": "m", "file": ["m.npz"]}}),
        doc("axes", {"mesh": {"kind": "shared", "per": "fixed", "units": "m", "axes": 1e300}}),
        doc("emptynpy", {"fields": {"q": "1"}}, "x,q\n1,empty.npy\n"),
        doc("missing", {}, "x,y,points\n1,2,missing.npy\n"),
        doc("wide", {}, "x,y\n1," + "1" * 140000 + "\n"),
    ]
    for path in documents:
        code, out, err = run(capsys, "build", path, "-o", str(tmp_path / "o.gamut"), "--json")
        assert code == 1 and json.loads(out)["problems"], (path, out, err)
        assert not (tmp_path / "o.gamut").exists()
    code, out, _ = run(capsys, "build", documents[0], "-o", p, "--json")         # an existing output
    assert code == 2 and "never replaced" in json.loads(out)["problems"][0]["message"]

    for argv in (["get", p, "absent", "-o", str(tmp_path / "a.csv")],
                 ["get", mesh, "q", "--zone", "absent=a", "-o", str(tmp_path / "z.csv")]):
        code, out, _ = run(capsys, *argv, "--json")
        assert code == 2 and json.loads(out)["problems"], (argv, out)

    # A value that is not one per row is refused for CSV, and --force keeps the output until then.
    kept = tmp_path / "coords.csv"
    kept.write_text("kept")
    code, out, _ = run(capsys, "get", mesh, "coordinates", "-o", str(kept), "--force", "--json")
    assert code == 2 and "not one per row" in json.loads(out)["problems"][0]["message"]
    assert kept.read_text() == "kept"

    # Text stored as invalid UTF-8 is shown, not raised; the validator calls it E3.
    with h5py.File(p, "r+") as f:
        f.attrs.create("writer", np.bytes_(b"\xff"))
    code, out, _ = run(capsys, "info", p, "--json")
    assert code == 0, out


def test_damaged_files_deep_documents_and_missing_folders(tmp_path, capsys):
    import h5py
    p = str(tmp_path / "t.gamut")
    with gamut.create(p, writer="t", parameters={"x": "1"}, scalars={"y": "1"},
                      labels={"status": {"role": "status", "categories": ["converged"]}}) as s:
        s.add_runs({"x": [1.0], "y": [2.0], "status": ["converged"]})
    damaged = str(tmp_path / "d.gamut")
    with open(p, "rb") as src, open(damaged, "wb") as dst:
        dst.write(src.read())
    with h5py.File(damaged, "r+") as f:
        del f["y"].attrs["units"]
        del f["status"].attrs["category"]
    code, out, err = run(capsys, "info", damaged)                       # text: no traceback
    assert code == 1 and "gamut validate" in err, (out, err)
    code, out, _ = run(capsys, "get", damaged, "status", "-o", str(tmp_path / "s.csv"), "--json")
    assert code == 1 and json.loads(out)["problems"][0]["rule"] == "E2"     # the file's, not a usage error

    deep = tmp_path / "deep.json"
    deep.write_text('{"writer":' + "[" * 1100 + "0" + "]" * 1100 + "}")
    code, out, _ = run(capsys, "build", str(deep), "-o", str(tmp_path / "n.gamut"), "--json")
    # Too deep for this Python's parser, or parsed and refused as a list: a document error either way.
    assert code == 1 and json.loads(out)["problems"], out

    for argv in (["get", p, "-o", str(tmp_path / "no" / "x.gamut")],
                 ["build", str(deep), "-o", str(tmp_path / "no" / "y.gamut")]):
        code, out, _ = run(capsys, *argv, "--json")
        assert code == 2 and "cannot create" in json.loads(out)["problems"][0]["message"], (argv, out)



def test_odd_outputs_and_self_append_are_usage_errors(tmp_path, capsys):
    p = str(tmp_path / "t.gamut")
    with gamut.create(p, writer="t", parameters={"x": "1"}) as s:
        s.add_runs({"x": [1.0, 2.0]})
    code, out, _ = run(capsys, "append", p, p, "--json")
    assert code == 2 and "one file" in json.loads(out)["problems"][0]["message"]
    long_name = str(tmp_path / ("a" * 300 + ".gamut"))
    code, out, _ = run(capsys, "get", p, "-o", long_name, "--json")
    assert code == 2 and "cannot create" in json.loads(out)["problems"][0]["message"]
    m = str(tmp_path / "m.gamut")
    with gamut.create(m, writer="t", mesh="shared", per="run", coordinates={"units": "m", "axes": 2},
                      parameters={"x": "1"}) as s:
        s.set_mesh(n_nodes=2)
        s.add_runs({"x": [1.0, 2.0]}, points=[np.zeros((2, 2)), np.ones((2, 2))])
    code, out, _ = run(capsys, "get", m, "coordinates", "-o", str(tmp_path / "c.csv"), "--json")
    assert code == 2 and "more than a CSV" in json.loads(out)["problems"][0]["message"]
    assert not (tmp_path / "c.csv").exists()



def test_rows_of_a_model_file_are_a_usage_error(tmp_path, capsys):
    data, model = str(tmp_path / "d.gamut"), str(tmp_path / "m.gamut")
    with gamut.create(data, writer="t", parameters={"x": "1"}) as s:
        s.add_runs({"x": [0.2, 0.8]})
    with gamut.create_model(model, writer="t", parameters={"x": {"units": "1", "lower": 0, "upper": 1}},
                            scalars={"y": {"units": "1", "model": "fit", "output": "y"}}) as s:
        s.add_model("fit", gamut.Nearest(["x"], [0.], [1.], [[0.], [1.]], {"y": [0., 2.]}), ["x"])
    (tmp_path / "runs.csv").write_text("x\n0.5\n")
    (tmp_path / "add.json").write_text(json.dumps({"runs": "runs.csv"}))
    for argv in (["get", model, "-o", str(tmp_path / "sub.gamut")], ["append", data, model],
                 ["append", model, str(tmp_path / "add.json")]):
        code, out, _ = run(capsys, *argv, "--json")
        assert code == 2 and "is a model file" in json.loads(out)["problems"][0]["message"], (argv, out)
    assert not (tmp_path / "sub.gamut").exists()




def test_appending_files_that_do_not_fit_together_is_a_usage_error(tmp_path, capsys):
    a, b = str(tmp_path / "a.gamut"), str(tmp_path / "b.gamut")
    with gamut.create(a, writer="t", parameters={"x": "1"}) as s:
        s.add_runs({"x": [1.0]})
    with gamut.create(b, writer="t", parameters={"x": "1"}, scalars={"y": "1"}) as s:
        s.add_runs({"x": [2.0], "y": [3.0]})
    code, out, _ = run(capsys, "append", a, b, "--json")
    assert code == 2 and "only in the source" in json.loads(out)["problems"][0]["message"], out



def test_documents_paths_and_permissions_have_their_exit_status(tmp_path, capsys):
    p = str(tmp_path / "t.gamut")
    with gamut.create(p, writer="t", parameters={"x": "1"}) as s:
        s.add_runs({"x": [1.0]})
    (tmp_path / "runs.csv").write_text("x\n2\n")
    add = tmp_path / "add.json"
    add.write_text(json.dumps({"runs": "runs.csv"}))
    code, out, _ = run(capsys, "append", p, str(tmp_path / "none.json"), "--json")
    assert code == 1 and "cannot read" in json.loads(out)["problems"][0]["message"]
    long_number = tmp_path / "long.json"
    long_number.write_text('{"writer": ' + "1" * 5000 + "}")
    code, out, _ = run(capsys, "build", str(long_number), "-o", str(tmp_path / "n.gamut"), "--json")
    assert code == 1 and json.loads(out)["problems"], out
    code, out, _ = run(capsys, "get", str(tmp_path / "none.gamut"), "-o", p, "--json")   # output first
    assert code == 2 and "never replaced" in json.loads(out)["problems"][0]["message"]
    if os.name != "nt":                      # argv carries bytes that are not UTF-8 as surrogates on POSIX
        odd = str(tmp_path / "bad\udcff.gamut")
        code, out, _ = run(capsys, "validate", odd, "--json")
        assert code == 1 and json.loads(out)["findings"][0]["rule"] == "E1", out
    os.chmod(p, 0o444)
    try:
        if not os.access(p, os.W_OK):                                   # not as root
            code, out, _ = run(capsys, "append", p, str(add), "--json")
            assert code == 2 and json.loads(out)["problems"], out
    finally:
        os.chmod(p, 0o644)

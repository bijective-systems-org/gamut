"""The command line, used the way an agent uses it: write a document and
files, build, inspect with --json, extract data to files."""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys

import numpy as np

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
    assert json.loads(out) == {"wrote": target, "rows": 4, "problems": []}

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
    assert code == 1 and "at nodes" in json.loads(out)["error"]["message"]


def test_vtk_command_without_its_extra_says_what_to_install():
    # A fresh interpreter, so no other test has imported pandas already.
    code = ("import sys; sys.modules['pandas'] = None; from gamut.cli import vtk_main; "
            "raise SystemExit(vtk_main(['--help']))")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 2, result.stderr
    assert 'pip install "gamut-format[vtk]"' in result.stderr
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
        assert code == 2 and json.loads(out)["error"]["message"].startswith("--zone"), (bad, out)


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

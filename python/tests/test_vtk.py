"""The VTK utility end to end: a folder of runs written with PyVista,
imported, read back with the library, exported and imported again."""

from __future__ import annotations

import json
import os

import numpy as np
import pytest

pv = pytest.importorskip("pyvista")
import mestra  # noqa: E402
from mestra import vtk as mestra_vtk  # noqa: E402


def plate(scale=1.0):
    grid = pv.ImageData(dimensions=(4, 3, 2)).cast_to_unstructured_grid()
    grid.points = grid.points * scale
    return grid


def write_runs(folder, n=3, morph=False, time=False):
    os.makedirs(folder, exist_ok=True)
    files = []
    for i in range(n):
        g = plate(1.0 + 0.1 * i if morph else 1.0)
        g.point_data["p"] = np.arange(g.n_points, dtype=np.float64) + 100 * i
        g.cell_data["U"] = (np.arange(g.n_cells * 3, dtype=np.float32).reshape(-1, 3) + i)
        g.cell_data["zone"] = np.array([0, 1] * (g.n_cells // 2) + [0] * (g.n_cells % 2),
                                       dtype=np.int32)
        name = f"run_{i:03d}.vtu"
        g.save(os.path.join(folder, name))
        files.append(name)
    return files


def fill_tables(folder, files, time=False):
    with open(os.path.join(folder, "parameters.csv"), "w") as fh:
        if time:
            fh.write("file,t,case\nunits,s,\nrole,time,group\n")
            for i, f in enumerate(files):
                fh.write(f"{f},{0.5 * i},{'a' if i < 2 else 'b'}\n")
        else:
            fh.write("file,mach,config\nunits,1,\n")
            for i, f in enumerate(files):
                fh.write(f"{f},{0.6 + 0.1 * i},{'clean' if i else 'flap'}\n")
    with open(os.path.join(folder, "fields.csv"), "w") as fh:
        fh.write("name,units\ncoordinates,m\np,Pa\nU,m s-1\n")


def test_first_call_writes_templates(tmp_path):
    folder = str(tmp_path / "runs")
    files = write_runs(folder)
    with open(os.path.join(folder, "._run_000.vtu"), "wb") as fh:     # macOS metadata
        fh.write(b"\0\5\26\7")
    report = mestra_vtk.import_folder(folder, str(tmp_path / "s.mes"))
    assert not report["ok"] and len(report["templates"]) == 2
    lines = open(os.path.join(folder, "parameters.csv")).read().splitlines()
    assert lines[:2] == ["file", "units"] and lines[2:] == files
    fields = open(os.path.join(folder, "fields.csv")).read().splitlines()
    assert fields == ["name,units", "coordinates,", "U,", "p,"]    # zone: a mesh label
    assert not os.path.exists(tmp_path / "s.mes")


def test_import_reads_back_and_round_trips(tmp_path):
    folder = str(tmp_path / "runs")
    files = write_runs(folder)
    fill_tables(folder, files)
    out = str(tmp_path / "s.mes")
    report = mestra_vtk.import_folder(folder, out)
    assert report["ok"], report
    assert report["geometry"] == "fixed" and report["mesh_labels"] == ["zone"]
    assert report["fields"] == ["U_x", "U_y", "U_z", "p"]
    assert report["notes"] == ["voxels stored as hexahedra"]
    with mestra.open(out) as s:
        assert s.row_count == 3 and s.type == "shared"
        assert s.get_label("file").tolist() == files
        assert s.get_label("config").tolist() == ["flap", "clean", "clean"]
        np.testing.assert_allclose(s.get_parameter("mach"), [0.6, 0.7, 0.8])
        assert s.describe("U_y")["vector"] == "U" and s.describe("U_y")["axis"] == "y"
        assert s.get_field("U_x").dtype == np.float32      # precision kept
        first = mestra_vtk.from_pyvista(pv.read(os.path.join(folder, files[1])))
        np.testing.assert_array_equal(s.get_field("p", rows=1), first["point_data"]["p"])
        np.testing.assert_array_equal(s.get_field("U_z", rows=1), first["cell_data"]["U"][:, 2])
        grid = mestra_vtk.to_pyvista(s, 2)
        original = pv.read(os.path.join(folder, files[2]))
        np.testing.assert_array_equal(grid.points, original.points)
        np.testing.assert_array_equal(grid.cell_data["U"], original.cell_data["U"])
        np.testing.assert_array_equal(grid.cell_data["zone"], original.cell_data["zone"])
    # Export and import again: the same study.
    back = str(tmp_path / "back")
    assert mestra_vtk.export_study(out, back)["ok"]
    again = str(tmp_path / "again.mes")
    assert mestra_vtk.import_folder(back, again)["ok"]
    with mestra.open(out) as a, mestra.open(again) as b:
        for name in ("p", "U_x", "U_y", "U_z"):
            np.testing.assert_array_equal(a.get_field(name), b.get_field(name))
        np.testing.assert_array_equal(a.get_parameter("mach"), b.get_parameter("mach"))
        assert a.get_label("config").tolist() == b.get_label("config").tolist()
        assert a.describe("mach")["units"] == b.describe("mach")["units"] == "1"
        for x, y in zip(a.get_cells(), b.get_cells()):
            np.testing.assert_array_equal(x, y)


def test_morphing_geometry_is_stored_per_run(tmp_path):
    folder = str(tmp_path / "runs")
    files = write_runs(folder, morph=True)
    fill_tables(folder, files)
    out = str(tmp_path / "s.mes")
    assert mestra_vtk.import_folder(folder, out)["geometry"] == "per run"
    with mestra.open(out) as s:
        np.testing.assert_array_equal(s.get_points(row=2),
                                      pv.read(os.path.join(folder, files[2])).points)


def test_runs_on_different_meshes_are_a_changing_mesh(tmp_path):
    folder = str(tmp_path / "runs")
    os.makedirs(folder)
    files = []
    for i, nx in enumerate((4, 5, 7)):                  # each run meshed on its own
        g = pv.ImageData(dimensions=(nx, 3, 2)).cast_to_unstructured_grid()
        g.point_data["p"] = np.arange(g.n_points, dtype=np.float64) + 100 * i
        g.cell_data["U"] = np.ones((g.n_cells, 3), dtype=np.float32) * i
        g.cell_data["zone"] = (np.arange(g.n_cells) % 2).astype(np.int32)
        files.append(f"run_{i:03d}.vtu")
        g.save(os.path.join(folder, files[-1]))
    fill_tables(folder, files)
    out = str(tmp_path / "s.mes")
    report = mestra_vtk.import_folder(folder, out)
    assert report["ok"] and report["geometry"] == "a mesh per run", report
    with mestra.open(out) as s:
        assert s.type == "changing"
        for row, f in enumerate(files):
            g = pv.read(os.path.join(folder, f))
            np.testing.assert_array_equal(s.get_points(row=row), g.points)
            np.testing.assert_array_equal(s.get_field("p", rows=row), g.point_data["p"])
            np.testing.assert_array_equal(s.get_mesh_label("zone", row=row), g.cell_data["zone"])
            assert len(s.get_cells(row=row)[0]) == g.n_cells
    back = str(tmp_path / "back")
    mestra_vtk.export_study(out, back)
    assert pv.read(os.path.join(back, files[2])).n_points == pv.read(os.path.join(folder, files[2])).n_points


def test_transients_get_their_run_group(tmp_path):
    folder = str(tmp_path / "runs")
    files = write_runs(folder)
    fill_tables(folder, files, time=True)
    out = str(tmp_path / "s.mes")
    assert mestra_vtk.import_folder(folder, out)["ok"]
    with mestra.open(out) as s:
        assert s.describe("t")["run_group"] == "case" and s.addons == ["time"]


def test_problems_are_reported_together(tmp_path):
    folder = str(tmp_path / "runs")
    files = write_runs(folder)
    other = plate()
    other = other.extract_cells([0, 1])                 # fewer cells: another mesh
    other.point_data["p"] = np.zeros(other.n_points)
    other.save(os.path.join(folder, files[1]))
    with open(os.path.join(folder, "parameters.csv"), "w") as fh:
        fh.write("file,mach,config\nunits,,\n")
        fh.write(f"{files[0]},0.6,a\n{files[1]},,b\n{files[2]},0.8,c\n")
    with open(os.path.join(folder, "fields.csv"), "w") as fh:
        fh.write("name,units\ncoordinates,m\np,Pa\n")
    with pytest.raises(mestra_vtk.Problems) as e:
        mestra_vtk.import_folder(folder, str(tmp_path / "s.mes"))
    text = "\n".join(e.value.problems)
    assert "line 4, column mach: blank" in text
    assert "column mach needs units" in text
    # The CSV problems stop the import before any VTK file is compared.
    with open(os.path.join(folder, "parameters.csv"), "w") as fh:
        fh.write("file,mach\nunits,1\n" + "".join(f"{f},0.5\n" for f in files))
    with pytest.raises(mestra_vtk.Problems) as e:
        mestra_vtk.import_folder(folder, str(tmp_path / "s.mes"))
    text = "\n".join(e.value.problems)
    assert f"{files[1]}: its arrays" in text
    assert not os.path.exists(tmp_path / "s.mes")


def test_bad_units_are_the_librarys_refusal(tmp_path):
    folder = str(tmp_path / "runs")
    files = write_runs(folder, n=2)
    fill_tables(folder, files)
    with open(os.path.join(folder, "fields.csv"), "w") as fh:
        fh.write("name,units\ncoordinates,m\np,Pa//s\nU,m s-1\n")
    out = str(tmp_path / "s.mes")
    with pytest.raises(mestra.MestraError) as e:
        mestra_vtk.import_folder(folder, out)
    assert e.value.rule == "E7" and "p" in e.value.path
    assert not os.path.exists(out)


def test_command_line_json(tmp_path, capsys):
    folder = str(tmp_path / "runs")
    files = write_runs(folder, n=2)
    assert mestra_vtk.main(["import", folder, "--json"]) == 2     # templates to fill in
    assert len(json.loads(capsys.readouterr().out)["templates"]) == 2
    fill_tables(folder, files)
    out = str(tmp_path / "s.mes")
    assert mestra_vtk.main(["import", folder, "-o", out, "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] and report["rows"] == 2
    assert mestra_vtk.main(["export", out, str(tmp_path / "out"), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["files"] == ["run_000.vtu", "run_001.vtu"]


def test_point_and_cell_arrays_sharing_a_name_are_both_kept(tmp_path):
    folder = str(tmp_path / "runs")
    files = write_runs(folder, n=2)
    for f in files:                                       # foamToVTK's habit
        g = pv.read(os.path.join(folder, f))
        g.cell_data["p"] = np.arange(g.n_cells, dtype=np.float64) + 0.5
        g.save(os.path.join(folder, f))
    fill_tables(folder, files)
    out = str(tmp_path / "s.mes")
    report = mestra_vtk.import_folder(folder, out)
    assert "p" in report["fields"] and "p_cell" in report["fields"]
    assert any("p_cell" in n for n in report["notes"])
    with mestra.open(out) as s:
        assert s.describe("p_cell")["location"] == "cell"
        np.testing.assert_array_equal(s.get_field("p_cell", rows=0), np.arange(6) + 0.5)


def test_a_name_two_arrays_give_is_refused(tmp_path):
    folder = str(tmp_path / "runs")
    files = write_runs(folder, n=2)
    for f in files:
        g = pv.read(os.path.join(folder, f))
        g.cell_data["U_x"] = np.zeros(g.n_cells)          # collides with U's x part
        g.save(os.path.join(folder, f))
    fill_tables(folder, files)
    with open(os.path.join(folder, "fields.csv"), "a") as fh:
        fh.write("U_x,m s-1\n")
    with pytest.raises(mestra_vtk.Problems) as e:
        mestra_vtk.import_folder(folder, str(tmp_path / "s.mes"))
    assert "both give the name U_x" in "\n".join(e.value.problems)


def test_export_names_stay_apart_and_csv_is_quoted(tmp_path):
    a, b = str(tmp_path / "a"), str(tmp_path / "b")
    for folder in (a, b):
        files = write_runs(folder, n=2)
        fill_tables(folder, files)
    with open(os.path.join(a, "parameters.csv"), "w") as fh:
        fh.write('file,mach,config\nunits,1,\nrun_000.vtu,0.6,"flaps, down"\nrun_001.vtu,0.7,clean\n')
    sa, sb = str(tmp_path / "a.mes"), str(tmp_path / "b.mes")
    assert mestra_vtk.import_folder(a, sa)["ok"] and mestra_vtk.import_folder(b, sb)["ok"]
    mestra.append(sa, sb)
    back = str(tmp_path / "back")
    files = mestra_vtk.export_study(sa, back)["files"]
    assert len(set(files)) == 4                            # none written twice
    again = str(tmp_path / "again.mes")
    assert mestra_vtk.import_folder(back, again)["ok"]
    with mestra.open(sa) as x, mestra.open(again) as y:
        assert x.get_label("config").tolist() == y.get_label("config").tolist()
        assert y.get_label("config")[0] == "flaps, down"
        np.testing.assert_array_equal(x.get_field("p"), y.get_field("p"))

"""VTK files in and out (needs the `vtk` extra: pip install mestra[vtk]).

A folder of VTK runs becomes one study with `mestra-vtk import`; a study
becomes one VTK file per run with `mestra-vtk export`. The same calls are
available from Python. The first import writes two small tables to fill in:
the parameters of each run, and the units of each array.
"""
import os
import shutil

import numpy as np
import pyvista as pv

from mestra import vtk
from _cylinder import pressure, ring

points, cells, t, r = ring()
folder = "runs"
shutil.rmtree(folder, ignore_errors=True)                  # start from a clean folder
os.makedirs(folder)
for k, gamma in enumerate((0.0, 2.0, 4.0)):
    types, offsets, connectivity = cells
    legacy = np.insert(connectivity, offsets[:-1], np.diff(offsets))
    grid = pv.UnstructuredGrid(legacy, types, np.column_stack([points, np.zeros(len(points))]))
    grid.point_data["cp"] = pressure(t, r, gamma=gamma)
    grid.save(f"{folder}/run_{k:03d}.vtu")

first = vtk.import_folder(folder, "from_vtk.mes")         # writes two tables, then stops
print("to fill in:", ", ".join(os.path.basename(t) for t in first["templates"]))
with open(f"{folder}/parameters.csv", "w") as table:
    table.write("file,gamma\nunits,m2 s-1\n" +
                "".join(f"run_{k:03d}.vtu,{g}\n" for k, g in enumerate((0.0, 2.0, 4.0))))
with open(f"{folder}/fields.csv", "w") as table:
    table.write("name,units\ncoordinates,m\ncp,1\n")
report = vtk.import_folder(folder, "from_vtk.mes")
print(report["rows"], "runs imported, geometry", report["geometry"])
print("written back:", vtk.export_study("from_vtk.mes", "back")["files"])

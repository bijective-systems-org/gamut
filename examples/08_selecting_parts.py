"""Reading only what you need: rows by condition, nodes by zone, units.

Runs are chosen with a small expression language; nodes by a mesh label;
values arrive in the units asked for (unit conversion needs the `units`
extra: pip install mestra[units]).
"""
import numpy as np

import mestra
from _cylinder import pressure, ring

points, cells, t, r = ring()
wall = (r == r.min()).astype(int)
with mestra.create("parts.mes", writer="example parts", mesh="shared", per="fixed",
                   coordinates={"units": "m", "axes": 2},
                   parameters={"gamma": {"units": "m2 s-1"}, "speed": {"units": "m s-1"}},
                   labels={"status": {"role": "status", "categories": ["converged", "failed"]}},
                   mesh_labels={"surface": {"at": "node", "categories": ["field", "wall"]}},
                   fields={"p": {"units": "Pa", "at": "node"}}) as study:
    study.set_mesh(points, cells, labels={"surface": wall})
    for speed in (10.0, 20.0, 40.0):
        for gamma in (0.0, 2.0, 4.0):
            q = 0.5 * 1.225 * speed**2                      # dynamic pressure, air at sea level
            study.add_run({"gamma": gamma, "speed": speed, "status": "converged"},
                          fields={"p": q * pressure(t, r, gamma=gamma)})

with mestra.open("parts.mes") as study:
    rows = study.select("speed >= 20 and gamma > 1 and status == converged")
    print("chosen rows:", rows)
    on_wall = np.flatnonzero(study.get_mesh_label("surface") == 1)
    p_wall = study.get_field("p", rows=rows, nodes=on_wall, units="kPa")
    print("wall pressure block:", p_wall.shape, "lowest", p_wall.min().round(3), "kPa")
    print("speeds in km/h:", study.get_parameter("speed", rows=rows, units="km/h").round(1))

"""A subset of AirfRANS, a public set of 2-D RANS runs around airfoils, as a
folder of VTK runs ready for `gamut-vtk import`.

    python bench/airfrans.py FOLDER [--runs 100]

AirfRANS (Bonnet et al., NeurIPS 2022 Datasets and Benchmarks, ODbL) holds
1,000 OpenFOAM simpleFoam runs, each on its own mesh of about 180,000
cells, in one 10 GB zip. This reads only the members it needs, by HTTP
range requests: the manifest, and the internal-field file of every fourth
run with a NACA 4-digit profile, in the zip's order, up to --runs. Each
run's file goes to FOLDER/<run>.vtu; parameters.csv takes the run's
inflow speed, angle of attack and the profile's three digits from its name,
and its split from the manifest; fields.csv gives every array's units.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import urllib.request
import zipfile

URL = "https://data.isir.upmc.fr/extrality/NeurIPS_2022/Dataset.zip"


class RangeFile(io.RawIOBase):
    """A remote file read by HTTP range requests, so zipfile can seek in it."""

    def __init__(self, url: str) -> None:
        with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=60) as r:
            self.size = int(r.headers["Content-Length"])
        self.url, self.pos = url, 0

    def seekable(self) -> bool:
        return True

    def readable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, offset: int, whence: int = 0) -> int:
        self.pos = {0: offset, 1: self.pos + offset, 2: self.size + offset}[whence]
        return self.pos

    def readinto(self, b) -> int:
        n = min(len(b), self.size - self.pos)
        if n <= 0:
            return 0
        headers = {"Range": f"bytes={self.pos}-{self.pos + n - 1}"}
        with urllib.request.urlopen(urllib.request.Request(self.url, headers=headers),
                                    timeout=300) as r:
            data = r.read()
        b[: len(data)] = data
        self.pos += len(data)
        return len(data)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("folder")
    ap.add_argument("--runs", type=int, default=100)
    args = ap.parse_args()
    os.makedirs(args.folder, exist_ok=True)
    z = zipfile.ZipFile(io.BufferedReader(RangeFile(URL), buffer_size=1 << 20))
    manifest = json.loads(z.read("Dataset/manifest.json"))
    test = set(manifest["full_test"])
    # A NACA 4-digit run's name: airFoil2D_SST_<speed>_<angle>_<m>_<p>_<t>.
    names = [i.filename.split("/")[1] for i in z.infolist() if i.filename.endswith("_internal.vtu")]
    four = [n for n in names if len(n.split("_")) == 7]
    chosen = four[::4][: args.runs]
    rows = []
    for name in chosen:
        target = os.path.join(args.folder, name + ".vtu")
        member = f"Dataset/{name}/{name}_internal.vtu"
        if not (os.path.exists(target) and os.path.getsize(target) == z.getinfo(member).file_size):
            with z.open(member) as src, open(target + ".part", "wb") as dst:
                while chunk := src.read(1 << 22):
                    dst.write(chunk)
            os.replace(target + ".part", target)
        speed, angle, m, p, t = name.split("_")[2:]
        rows.append(f"{name}.vtu,{speed},{angle},{m},{p},{t},{'test' if name in test else 'train'}")
        print(name, flush=True)
    with open(os.path.join(args.folder, "parameters.csv"), "w") as fh:
        fh.write("file,inflow_speed,angle_of_attack,naca_m,naca_p,naca_t,split\n"
                 "units,m s-1,degree,1,1,1,\n"
                 "role,condition,condition,design,design,design,split\n")
        fh.write("\n".join(rows) + "\n")
    with open(os.path.join(args.folder, "fields.csv"), "w") as fh:
        # Incompressible OpenFOAM: p is pressure over density.
        fh.write("name,units\ncoordinates,m\np,m2 s-2\nU,m s-1\nnut,m2 s-1\n"
                 "implicit_distance,m\n")


if __name__ == "__main__":
    main()

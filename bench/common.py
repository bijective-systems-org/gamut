"""What every benchmark shares: timing, sizes, and a record of the machine."""

from __future__ import annotations

import json
import os
import platform
import statistics
import subprocess
import sys
import time
from importlib import metadata
from typing import Any, Callable

REPEATS = 5


def timed(work: Callable[[], Any], repeats: int = REPEATS) -> dict[str, Any]:
    """The median and spread of `repeats` timed calls, after one untimed call
    that warms the operating system's file cache."""
    work()
    seconds = []
    for _ in range(repeats):
        start = time.perf_counter()
        work()
        seconds.append(time.perf_counter() - start)
    return {"median_s": statistics.median(seconds), "min_s": min(seconds),
            "max_s": max(seconds), "repeats": repeats}


def size_of(path: str) -> int:
    """Bytes of a file, or of every file under a folder (not the "._" files
    macOS writes beside others on some drives)."""
    if os.path.isfile(path):
        return os.path.getsize(path)
    return sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(path) for f in fs
               if not f.startswith("._"))


def machine() -> dict[str, Any]:
    """The machine and the versions behind a result."""
    info: dict[str, Any] = {"python": platform.python_version(), "system": platform.platform()}
    if sys.platform == "darwin":
        for key, name in (("machdep.cpu.brand_string", "cpu"), ("hw.memsize", "memory_bytes"),
                          ("hw.ncpu", "cores")):
            out = subprocess.run(["sysctl", "-n", key], capture_output=True, text=True).stdout
            info[name] = out.strip()
    packages = {}
    for name in ("mestra", "numpy", "h5py", "netCDF4", "xarray", "zarr", "pyarrow", "pandas",
                 "pyvista", "vtk"):
        try:
            packages[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            pass
    info["packages"] = packages
    here = os.path.dirname(os.path.abspath(__file__))
    commit = subprocess.run(["git", "-C", here, "rev-parse", "--short", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", here, "status", "--porcelain", "--", "src", "include",
                            "python/mestra"], capture_output=True, text=True).stdout.strip()
    info["source"] = commit + (" (modified)" if dirty else "")
    return info


def run_child(script: str, *args: str) -> Any:
    """Runs one measurement in a fresh process (so no library's cache serves
    another) and returns the JSON it prints."""
    out = subprocess.run([sys.executable, script, *args], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"{script} {' '.join(args)} failed:\n{out.stderr[-2000:]}")
    return json.loads(out.stdout.strip().splitlines()[-1])

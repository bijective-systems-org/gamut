# Benchmarks

The scripts behind [docs/benchmarks.md](../docs/benchmarks.md). Each writes
a study in every format from the same data, measures each format in a fresh
process, checks that every format read the same numbers, and saves a JSON
result with the machine and the versions.

```bash
pip install "gamut-format[vtk]" h5py netCDF4 xarray zarr pyarrow

# A study on one mesh (any gamut file with a shared mesh):
python bench/shared_mesh.py run STUDY.gamut WORK_DIR bench/results/NAME.json

# A folder of VTK runs on their own meshes; this fetches 100 runs of
# AirfRANS (1.5 GB) by range requests from its 10 GB zip:
python bench/airfrans.py AIRFRANS_DIR
python bench/changing_mesh.py run AIRFRANS_DIR WORK_DIR bench/results/airfrans.json

# The page's tables and figures, from bench/results/:
python bench/figures.py
```

`shared_mesh.py` reads pressure by default; `--field`, `--row`, `--node`,
`--region`, `--where` and `--scalar` choose other reads for another study.
The capsule family on the page is not public; any shared-mesh study gives
the same comparison.

Run one benchmark at a time on an otherwise quiet machine, with the work
directory on the machine's own disk.

## Native simulation formats

`study_formats.py` adds native Exodus II and CGNS result files, official
PhysicsNeMo-Mesh serialization, and a matched h5py read of the Gamut file
itself. It measures scalar node fields on a shared topology with one cell
type. Every geometry has one native file containing all its runs, with a
CSV/schema companion counted in its size. The complete ordered fields,
meshes and run tables must match before timing. These are benchmark layouts,
not new converter products.

Use an isolated environment with numpy, pandas, h5py, Gamut and, for PMSH,
nvidia-physicsnemo and its dependencies. Native libraries are explicit:

```bash
export CGNS_LIBRARY=/path/to/libcgns
export CGNS_INDEX_BYTES=8        # cgsize_t in that installation's cgnstypes.h
export EXODUS_LIBRARY=/path/to/libexodus
export EXODUS_API_VERSION=904   # EX_API_VERS_NODOT in that exodusII.h
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
python bench/study_formats.py run naca4412.gamut WORK_DIR bench/results/xfoil_native.json \
  --field cp --scalar cl --row 100 --node 12 --region 0:80 \
  --where 'alpha > 5 and reynolds > 1000000'
```

Library names/extensions depend on the platform. The bindings also accept
VTK's prefixed native libraries. The ABI values must match those libraries;
they are not inferred from a filename. `Mesh.save/load` is used unchanged,
on CPU; reads consume the tensors rather than timing mapping handles alone.
PMSH requires simplices. For the quadrilateral capsule study, select
`--formats gamut gamut_threads exodus exodus_gzip cgns h5py`.

Do not add newly measured rows to an older result file. Run all selected
peers together, keep input/source hashes and package versions, and regenerate
`docs/benchmarks.md` and its figures with `python bench/figures.py`.

# Benchmarks

The scripts behind [docs/benchmarks.md](../docs/benchmarks.md). Each writes
a study in every format from the same data, measures each format in a fresh
process, checks that every format read the same numbers, and saves a JSON
result with the machine and the versions.

```bash
pip install "mestra[vtk]" h5py netCDF4 xarray zarr pyarrow

# A study on one mesh (any mestra file with a shared mesh):
python bench/shared_mesh.py run STUDY.mes WORK_DIR bench/results/NAME.json

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

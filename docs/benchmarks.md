# Benchmarks

What a study costs on disk and how fast its common reads are, as one Gamut
file and in the forms teams use today. Two studies of different shapes, the
same reads, every format written from the same data and checked to return
the same numbers.

## What the numbers say

- **Size.** One Gamut file takes a sixth of the space of the folder of VTK
  files the capsule family came as, and half for AirfRANS. The others take
  about the same: netCDF 2 % less, Zarr 2 % more, and HDF5 written a run at
  a time with the same filters 2 % to 18 % more.
- **One run** reads in about a millisecond on the capsule family's small
  mesh, most of it opening the file; HDF5 written a run at a time is
  faster there (0.26 ms), Zarr and netCDF slower. On an AirfRANS mesh it
  takes 15 ms, as HDF5 does, eight times faster than the run's VTK file.
- **Runs by condition** take a millisecond: about as fast as a Parquet
  table and sixty times faster than visiting HDF5 run by run. Reading AirfRANS's
  small parameters.csv is faster still.
- **Reads across runs are Gamut's slowest.** Its default chunks are shaped
  for reading whole runs, so on a small mesh one node across all 1,364 runs
  decompresses the whole field: 124 ms, or 38 ms with four threads. Zarr's
  default chunks take 4 ms, netCDF 54 ms and HDF5 run by run 80 ms; 1,364
  VTK files take 5 s.
- **Writing** the capsule family takes 1.2 s, against 10.6 s for the VTK
  files; Zarr writes fastest, with zstd on many threads, while Gamut uses
  gzip, which every netCDF and HDF5 reader can decompress. Importing
  AirfRANS is slower than the other conversions (55 s against 31 s for
  HDF5), because the importer reads every file twice: once to check the
  whole folder before it writes anything.

## The two studies

**A capsule family.** Our own: 44 capsule shapes meshed with one topology
by a mapping tool, each run at 31 conditions (Mach number, angle of attack,
sideslip), with surface pressure and heating from engineering methods
(modified Newtonian pressure, laminar heating by Lees' similarity) on
6,722 nodes. Many runs, a small mesh, the geometry per shape. Not public.

**AirfRANS.** Public: 100 runs of the AirfRANS dataset (Bonnet et al.,
NeurIPS 2022; ODbL), two-dimensional RANS solutions around NACA 4-digit
airfoils from OpenFOAM, each on its own mesh of about 177,000 nodes, with
pressure, velocity and turbulent viscosity at nodes and cells. Few runs,
large meshes, a mesh per run. `bench/airfrans.py` fetches the same subset.

## Size on disk

<p align="center"><img src="assets/bench-size.svg" alt="Size on disk of each format, relative to the folder of VTK files" width="680"></p>

## Reads

<p align="center"><img src="assets/bench-one-node.svg" alt="Time to read one node across every run of the capsule family, by format" width="680"></p>

<p align="center"><img src="assets/bench-one-run.svg" alt="Time to read one run's points and pressure from AirfRANS, by format" width="680"></p>

### The capsule family

<!-- results: capsule -->
| Format | Size | Write | Open | One run | One node, every run | A region, every run | Runs by condition |
|---|---:|---:|---:|---:|---:|---:|---:|
| **Gamut** | 66 MB | 1.23 s | 808 µs | 1.18 ms | 124 ms | 127 ms | 1.04 ms |
| **Gamut, 4 threads** | 66 MB | — | 806 µs | 1.18 ms | 37.8 ms | 38.2 ms | 1.04 ms |
| VTK folder | 419 MB | 10.6 s | 2.26 ms | 2.82 ms | 4.9 s | 3.86 s | 2.38 ms |
| VTK folder, zipped | 295 MB | 12.1 s | — | — | — | — | — |
| HDF5, a group per run | 77.8 MB | 2.16 s | 293 µs | 255 µs | 80.1 ms | 87 ms | 63.5 ms |
| netCDF-4 (xarray) | 64.6 MB | 1.49 s | 5.09 ms | 56.1 ms | 54.4 ms | 75.6 ms | 6.65 ms |
| Zarr (xarray) | 67.5 MB | 215 ms | 2.41 ms | 4.68 ms | 4.29 ms | 5.2 ms | 3.67 ms |
| Parquet, run table only | 0.14 MB | 99 ms | — | — | — | — | 893 µs |
<!-- end -->

### AirfRANS

<!-- results: airfrans -->
| Format | Size | Write | Open | One run | Runs by condition |
|---|---:|---:|---:|---:|---:|
| VTK folder | 1.46 GB | — | 330 µs | 124 ms | 420 µs |
| VTK folder, zipped | 976 MB | 42.4 s | — | — | — |
| **Gamut** | 710 MB | 55 s | 703 µs | 15.3 ms | 728 µs |
| HDF5, a group per run | 725 MB | 31.3 s | 84 µs | 16.3 ms | 2.99 ms |
<!-- end -->

## How it was measured

- **Formats.** Gamut; the folder of VTK files the runs came as (written
  by PyVista with its defaults for the capsule family, the published files
  for AirfRANS) with a `parameters.csv` of the run table; that folder
  zipped; HDF5 written with h5py, a group per run with each field a
  dataset compressed as Gamut's are (shuffle, then gzip) and the run's
  parameters as attributes; netCDF-4 and Zarr written by xarray with their
  default chunking and compression (shuffle and zlib for netCDF, zstd for
  Zarr); and the run table alone as Parquet. Gamut uses gzip level 1, the
  HDF5 and netCDF copies level 4. netCDF and Zarr have no standard layout for a set of different
  meshes, so they appear for the capsule family only. The AirfRANS files
  carry three integer id arrays that the Gamut and HDF5 copies leave out.
- **Reads.** *Open*: open the study and list what it holds. *One run*: one
  run's pressure (with its points, for AirfRANS). *One node, every run* and
  *a region, every run*: the pressure at one node, or at 672 consecutive
  nodes, in all 1,364 runs. *Runs by condition*: choose the runs with Mach
  number above 20 and positive angle of attack (inflow speed above 50 m/s
  and angle above 5°, for AirfRANS) and read a result of each.
- **Timing.** Each format is measured in a fresh process, so no library's
  cache serves another. Each read opens and closes the file, as a script
  does. Times are the median of five, after one untimed read; the files
  are in the operating system's cache (clearing it needs administrator
  rights), so they measure decoding and library work rather than the disk.
  Writes are timed once, from arrays in memory (the capsule family) or
  from the published VTK files (AirfRANS, where every format reads them).
  From one run of the whole benchmark to the next, medians moved by up to
  a third.
- **Checks.** For every read, every format returns the same numbers.
- **Machine.**
<!-- results: machine -->
Apple M3, 8 GB, macOS-27.0.1-arm64-arm-64bit; Python 3.11.11; gamut 1.0.0.dev0, numpy 2.4.6, h5py 3.16.0, netCDF4 1.7.5, xarray 2026.9.0, zarr 3.1.6, pyarrow 26.0.0, pandas 3.0.6, pyvista 0.49.1, vtk 9.7.1; Gamut built from 1cbf047.
<!-- end -->

The scripts are in [`bench/`](../bench), the results beside them in
`bench/results/`, and this page's tables and figures are generated from
those results by `bench/figures.py`.

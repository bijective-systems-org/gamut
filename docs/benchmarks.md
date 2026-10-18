# Benchmarks

What a study costs on disk and how fast its common reads are, as one Gamut
file and in the forms teams use today. Two studies of different shapes, the
same reads, every format written from the same data and checked to return
the same numbers.

## Summary

One Gamut file takes a sixth of the space of the folder of VTK files the
capsule family came as, and half for AirfRANS. netCDF-4 and Zarr take
about the same (2 % less and 2 % more), HDF5 written a run at a time 18 %
more and VTKHDF 20 % more. NumPy files are larger: 2.3 times uncompressed,
3.8 times as a compressed file per run, because every run carries its own
copy of the shape's points.

One run reads in about a millisecond on the capsule family's small mesh,
most of it spent opening the file (0.9 ms). Read straight with h5py,
VTKHDF opens in a tenth of that and HDF5 in a third, and each reads one
run in 0.3 ms, uncompressed NumPy arrays in 0.09 ms. Zarr takes 5 ms and
netCDF-4 58 ms.
On an AirfRANS mesh one run takes 15 ms, as in HDF5, eight times faster
than reading the run's VTK file.

Choosing runs by condition and reading a result of each takes 1.2 ms, as
fast as a Parquet file of the run table and sixty times faster than
visiting HDF5 run by run. VTKHDF, whose run table is a few plain arrays
read with h5py, takes 0.2 ms; the CSV files beside the VTK and NumPy
copies take about 2.4 ms. Reading AirfRANS's small `parameters.csv` is
faster than Gamut too.

Reads across runs are where Gamut is slowest. Its default chunks are
shaped for reading whole runs, so on a small mesh one node across all
1,364 runs decompresses the whole field: 127 ms, or 39 ms with four
threads. Uncompressed NumPy takes 0.7 ms, Zarr's default chunks 5 ms,
netCDF-4 57 ms, HDF5 run by run 88 ms and VTKHDF 165 ms; 1,364 VTK files
take 4.2 s.

Writing the capsule family takes 1.2 s, against 1.3 s for VTKHDF and
10.7 s for the VTK files. Zarr and uncompressed NumPy write fastest,
0.18 s each, Zarr with zstd on many threads, while Gamut uses gzip, which
every netCDF and HDF5 reader can decompress. Importing AirfRANS is slower
than the other conversions (55 s against 31 s for HDF5), because the
importer reads every file twice, once to check the whole folder before it
writes anything.

## The two studies

The capsule family is our own: 44 capsule shapes meshed with one topology
by a mapping tool, each run at 31 conditions (Mach number, angle of
attack, sideslip), with surface pressure and heating from engineering
methods (modified Newtonian pressure, laminar heating by Lees' similarity)
on 6,722 nodes. It has many runs, a small mesh, and a geometry per shape.
It is not public.

AirfRANS is public: 100 runs of the AirfRANS dataset (Bonnet et al.,
NeurIPS 2022; ODbL), two-dimensional RANS solutions around NACA 4-digit
airfoils from OpenFOAM, each on its own mesh of about 177,000 nodes, with
pressure, velocity and turbulent viscosity at nodes and cells. It has few
runs, large meshes, and a mesh per run. `bench/airfrans.py` fetches the
same subset.

## Size on disk

<p align="center"><img src="assets/bench-size.svg" alt="Size on disk of each format, relative to the folder of VTK files" width="680"></p>

## Reads

<p align="center"><img src="assets/bench-one-node.svg" alt="Time to read one node across every run of the capsule family, by format" width="680"></p>

<p align="center"><img src="assets/bench-one-run.svg" alt="Time to read one run's points and pressure from AirfRANS, by format" width="680"></p>

### The capsule family

<!-- results: capsule -->
| Format | Size | Write | Open | One run | One node, every run | A region, every run | Runs by condition |
|---|---:|---:|---:|---:|---:|---:|---:|
| **Gamut** | 66 MB | 1.19 s | 894 µs | 1.26 ms | 127 ms | 128 ms | 1.15 ms |
| **Gamut, 4 threads** | 66 MB | — | 896 µs | 1.26 ms | 38.8 ms | 40.3 ms | 1.18 ms |
| VTK folder | 419 MB | 10.7 s | 2.27 ms | 2.9 ms | 4.24 s | 3.89 s | 2.47 ms |
| VTK folder, zipped | 295 MB | 11.8 s | — | — | — | — | — |
| VTKHDF, a step per run | 79.1 MB | 1.32 s | 97 µs | 334 µs | 165 ms | 172 ms | 196 µs |
| HDF5, a group per run | 77.8 MB | 2.09 s | 293 µs | 279 µs | 88.3 ms | 93.7 ms | 74 ms |
| netCDF-4 (xarray) | 64.6 MB | 1.47 s | 5.61 ms | 58.1 ms | 57.2 ms | 78.9 ms | 5.95 ms |
| Zarr (xarray) | 67.5 MB | 179 ms | 2.41 ms | 5.01 ms | 4.75 ms | 5.61 ms | 3.82 ms |
| NumPy, a file per run | 254 MB | 6.92 s | 3.28 ms | 855 µs | 273 ms | 252 ms | 2.42 ms |
| NumPy arrays, uncompressed | 154 MB | 179 ms | 2.16 ms | 91 µs | 697 µs | 1.49 ms | 2.24 ms |
| Parquet, run table only | 0.14 MB | 447 ms | — | — | — | — | 1.32 ms |
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

### Formats

Gamut; the folder of VTK files the runs came as (written by PyVista with
its defaults for the capsule family, the published files for AirfRANS)
with a `parameters.csv` of the run table; that folder zipped; HDF5 written
with h5py, a group per run with each field a dataset compressed as Gamut's
are (shuffle, then gzip) and the run's parameters as attributes; netCDF-4
and Zarr written by xarray with their default chunking and compression
(shuffle and zlib for netCDF, zstd for Zarr); and the run table alone as
Parquet. Gamut uses gzip level 1, the HDF5 and netCDF copies level 4.
netCDF and Zarr have no standard layout for a set of different meshes, so
they appear for the capsule family only. The AirfRANS files carry three
integer id arrays that the Gamut and HDF5 copies leave out.

For the capsule family there are three more. VTKHDF 2.2 holds the study
as an unstructured grid with one time step per run: each shape's points
stored once, each field chunked a step at a time and compressed as the
HDF5 copy is, and the run table's number columns as field data; VTK's own
reader opens it, and the benchmark reads it with h5py. A compressed NumPy
file per run (`numpy.savez_compressed`) and one uncompressed `.npy` array
per field, read memory-mapped, each come with a `parameters.csv`. The
NumPy copies hold the fields, the points and the run table, but not the
cells. CGNS is not measured: it has no Python writer that installs without
building its library.

### Reads

*Open* opens the study and lists what it holds. *One run* reads one run's
pressure (with its points, for AirfRANS). *One node, every run* and *a
region, every run* read the pressure at one node, or at 672 consecutive
nodes, in all 1,364 runs. *Runs by condition* chooses the runs with Mach
number above 20 and positive angle of attack (inflow speed above 50 m/s
and angle above 5°, for AirfRANS) and reads a result of each.

### Timing

Each format is measured in a fresh process, so no library's cache serves
another. Each read opens and closes the file, as a script does. Times are
the median of five, after one untimed read. The files are in the
operating system's cache (clearing it needs administrator rights), so the
times measure decoding and library work rather than the disk. Writes are
timed once, from arrays in memory (the capsule family) or from the
published VTK files (AirfRANS, where every format reads them). From one
run of the whole benchmark to the next, medians moved by up to a third.
During the capsule run another process used one of the machine's eight
cores part of the time. Against an earlier run without it, every read's
median was within 17 %, faster or slower, except Parquet's (893 µs then,
1.32 ms now).

For every read, every format returns the same numbers.

### Machine

<!-- results: machine -->
Apple M3, 8 GB, macOS-27.0.1-arm64-arm-64bit; Python 3.11.11; gamut 1.0.0.dev0, numpy 2.4.6, h5py 3.16.0, netCDF4 1.7.5, xarray 2026.9.0, zarr 3.1.6, pyarrow 26.0.0, pandas 3.0.6, pyvista 0.49.1, vtk 9.7.1; Gamut built from 0893621.
<!-- end -->

The scripts are in [`bench/`](../bench), the results beside them in
`bench/results/`, and this page's tables and figures are generated from
those results by `bench/figures.py`.

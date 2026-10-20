# Benchmarks

Gamut combines compressed array storage with a defined simulation study:
inputs, meshes, results, units and run relationships, accessed through the
same study vocabulary in Python, MATLAB, Julia, C++ and C. These benchmarks
measure the storage and read costs of that choice. The [comparison](comparison.md)
explains each format's purpose and interoperability; timings alone do not
measure clarity or language support.

HDF5 and netCDF-4 are Gamut's foundations. A matched h5py baseline below
reads the **same Gamut file**, with identical arrays, chunks and filters.
It measures direct storage access beside the study interface. The older
"HDF5, a group per run" result measures one custom layout, not HDF5's limits.

## Native simulation formats — 20 October 2026

Exodus II and CGNS are measured through their native C libraries, called
from Python. PhysicsNeMo-Mesh uses NVIDIA's official `Mesh.save` and
`Mesh.load` on CPU. These are measurements of the stated layouts, libraries
and settings, rather than an intrinsic ranking of format names.

### A geometry family

The capsule study has 1,364 runs on 44 geometries sharing one topology:
6,722 nodes and 6,720 quadrilaterals, with pressure and heating from
engineering methods. It is not CFD validation. Each native result file
holds one geometry and all 31 of its runs, avoiding a file per run.

<!-- results: capsule_native -->
| Format | Size | Write | One run | One node, every run | A region, every run | Runs by condition |
|---|---:|---:|---:|---:|---:|---:|
| **Gamut** | 66 MB | 1.39 s | 1.86 ms | 121 ms | 133 ms | 1.87 ms |
| **Gamut, 4 threads** | 66 MB | — | 1.92 ms | 25.2 ms | 26.6 ms | 2.02 ms |
| Exodus II, native defaults | 160 MB | 327 ms | 6.06 ms | 73.1 ms | 113 ms | 4.44 ms |
| Exodus II, gzip 1 + shuffle | 67.9 MB | 1.19 s | 5.74 ms | 183 ms | 225 ms | 4.35 ms |
| CGNS, native defaults | 167 MB | 485 ms | 22.7 ms | 836 ms | 844 ms | 4.16 ms |
| Storage baseline: same file via h5py | 66 MB | — | 492 µs | 126 ms | 138 ms | 310 µs |
<!-- end -->

Gamut and compressed Exodus occupy about the same space. Gamut reads a
whole run and queries this run table faster in these implementations.
A node across every run is expensive for Gamut's default chunks; the four
thread read reduces that cost. The matched h5py row makes both the fixed
interface cost on small reads and similar bulk decoding cost visible.
PMSH is not measured on this quadrilateral mesh: its mesh model requires
simplices, and this comparison does not triangulate just one peer's input.

### An airfoil sweep

The NACA 4412 XFOIL 6.99 sweep used by the README picture has 363 runs on
one fixed 160-node mesh of line segments, with pressure coefficient and
skin friction. Its simplicial mesh permits the PMSH comparison.

<!-- results: xfoil_native -->
| Format | Size | Write | One run | One node, every run | A region, every run | Runs by condition |
|---|---:|---:|---:|---:|---:|---:|
| **Gamut** | 0.825 MB | 16.9 ms | 1.62 ms | 2.2 ms | 2.24 ms | 1.04 ms |
| **Gamut, 4 threads** | 0.825 MB | — | 1.4 ms | 1.37 ms | 1.4 ms | 1.07 ms |
| Exodus II, native defaults | 1.02 MB | 53 ms | 1.72 ms | 2.25 ms | 12.3 ms | 595 µs |
| Exodus II, gzip 1 + shuffle | 0.945 MB | 55.1 ms | 2.12 ms | 4.81 ms | 15.1 ms | 618 µs |
| CGNS, native defaults | 1.65 MB | 85.6 ms | 199 ms | 207 ms | 211 ms | 592 µs |
| PhysicsNeMo-Mesh (PMSH) | 0.96 MB | 39 ms | 1.16 ms | 1.13 ms | 1.18 ms | 576 µs |
| Storage baseline: same file via h5py | 0.825 MB | — | 865 µs | 1.44 ms | 1.42 ms | 186 µs |
<!-- end -->

For this small sweep, PMSH's memory-mapped representation reads faster
than Gamut, while Gamut is smaller. Direct h5py and the CSV run tables can
also answer the small numeric query faster than Gamut's study interface.
Those results are useful boundaries on the convenience and portability
claim; Gamut is not the fastest path for every operation.

### What the copies contain

Every copy contains the same run table, node fields, coordinates and
connectivity, including missing results and failed-run labels. Native
copies include `runs.csv` (row to geometry/solution mapping) and
`schema.json` (the copied units and declarations); their bytes are counted.
Constants, node labels, uncertainty, gradients and notes are outside this
common payload, so these are not whole-file archival conversion tests.
Untimed checks compare complete ordered arrays, meshes and tables, with
NaNs preserved, before any read is timed. Timed reads consume the values;
a PMSH mapping handle alone does not count as reading its data.

| Representation | Layout and settings |
|---|---|
| Gamut | One study, default chunks, shuffle and gzip level 1; float64 fields |
| Exodus II | One netCDF-4 result file per geometry; each run is a time index, with float64 nodal variables. Native defaults are uncompressed; a second row enables gzip level 1 and shuffle through `ex_set_option` |
| CGNS | One HDF5-backed file per geometry, with a `FlowSolution_t` per run and float64 vertex fields; native storage defaults, without gzip |
| PMSH | One official `Mesh` per geometry; each point field is a nodes × runs tensor, with float64 values and uncompressed memory-mapped storage |
| Same file via h5py | Gamut's actual datasets and slices, without the study interface or its metadata interpretation |

The use of Exodus time indices, CGNS solution names and PMSH tensor columns
for parametric runs is a benchmark convention. Their CSV/schema companions
supply the study mapping; these timings do not imply those conventions are
native standards. CGNS open traverses its solution tree, which matters for
these many-solution files. No claim about ordinary API ease follows from
these benchmark bindings. No GPU, training throughput or cloud access is
measured.

Each read includes opening/closing the file and any CSV/schema access it
needs. Imports are outside the clocks. Each operation has one warm-up and
five timed reads; the tables show medians, with min/max in the JSON. Files
are in the OS cache, so these measure library work and decoding rather
than cold disk throughput. Writes are timed once from arrays already in
memory. Runs are serial, with BLAS/OpenMP limited to one thread; Gamut's
explicit four-thread row uses four decompression workers. Other desktop
applications remain open, so small timing differences should not be ranked.

<!-- results: machine_native -->
Apple M3, 8 GB, macOS-27.0.1-arm64-arm-64bit; Python 3.11.11; gamut 1.1.0, numpy 2.3.5, h5py 3.15.1, netCDF4 1.7.4, xarray 2026.2.0, zarr 3.1.6, pyarrow 23.0.1, pandas 2.3.3, pyvista 0.48.1, vtk 9.5.2, nvidia-physicsnemo 2.2.2, tensordict 0.15.2, torch 2.13.0; Gamut built from beab197.
<!-- end -->

Native libraries: CGNS 4.5.0 (64-bit `cgsize_t`) and Exodus 9.04, distributed
as VTK-prefixed libraries in this environment. The JSON records each measurement's source commit. The
source's package version remains 1.1.0 and includes the unreleased open/
validator changes; these are not measurements of the PyPI 1.1.0 wheel.

### Repeating the native comparisons

Install the benchmark dependencies in an isolated environment. Use actual
CGNS/Exodus shared libraries and the ABI values in their installed headers:

```bash
export CGNS_LIBRARY=/path/to/libcgns
export CGNS_INDEX_BYTES=8          # sizeof(cgsize_t), from cgnstypes.h
export EXODUS_LIBRARY=/path/to/libexodus
export EXODUS_API_VERSION=904     # EX_API_VERS_NODOT, from exodusII.h
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
python bench/study_formats.py run naca4412.gamut WORK_DIR bench/results/xfoil_native.json \
  --field cp --scalar cl --row 100 --node 12 --region 0:80 \
  --where 'alpha > 5 and reynolds > 1000000'
```

The XFOIL input can be generated by `docs/assets/hero_sweep.py`; the capsule
input is private. Regenerated solver results can differ from the retained
input, so rerun all peers together rather than attaching new rows to these
old timings. The bindings also accept the prefixed libraries supplied by
VTK; no replacement serializer is used. `--formats` selects peers explicitly.
For a quadrilateral study, omit `pmsh`. The scripts and results are in
[`bench/`](../bench); `python bench/figures.py` regenerates tables and figures.

## Reading the study, in the same vocabulary

The [README's examples](../README.md#example) write, append and read the
same study in four languages, with matching numeric output. The runnable
[reading-parts example](guide/08-reading-parts.md) selects converged runs,
reads a named surface region and converts pressure to kilopascals. Those
examples demonstrate the interface; they are not a subjective ease-of-use
score or a claim that other scientific formats lack metadata or language APIs.

## Earlier storage-layout measurements

The following results are retained from Gamut 1.0.0.dev0 at `0893621`.
They compare existing VTK files, VTKHDF and several array/table layouts.
Their package versions, omissions and original measurement method remain
below. They were measured separately from the native-format tables above;
do not calculate speed ratios between the two runs.

## The two studies

The capsule family is our own: 44 capsule shapes meshed with one topology
by a mapping tool, each run at 31 conditions (Mach number, angle of
attack, sideslip), with surface pressure and heating from engineering
methods (modified Newtonian pressure, laminar heating by Lees' similarity)
on 6,722 nodes. It has many runs, a small mesh, and a geometry per shape.
It is not public.

AirfRANS is public: 100 runs of the AirfRANS dataset (Bonnet et al.,
NeurIPS 2022; ODbL), two-dimensional RANS solutions around NACA 4-digit
airfoils from OpenFOAM, each on its own mesh of about 176,000 nodes, with
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

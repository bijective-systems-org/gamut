# Installing Gamut (gamut-format)

Gamut is published by Bijective Systems as
[`gamut-format` on PyPI](https://pypi.org/project/gamut-format/).
Install `gamut-format`, then `import gamut`; the command line is `gamut`.
The PyPI project named `gamut` is a different package.

Every language uses the same core library, written in C++. The Python
wheels include it, with HDF5 linked inside, so it never meets another HDF5
in the same process: h5py's, MATLAB's or a solver's. MATLAB and Julia can
use the wheel's copy; C++ and C programs build the core from source.

## Python

```bash
pip install gamut-format                 # Python 3.10 or later
pip install "gamut-format[units]"        # with unit conversion on reads and writes (pint)
pip install "gamut-format[vtk]"          # with VTK import and export (pyvista, pandas)
```

Wheels are built for macOS (arm64 and x86_64, macOS 11 and later), Linux
(x86_64, glibc 2.28 and later) and Windows (x86_64). One wheel serves every Python version on its
platform. The only required dependency is NumPy, 1.26 or later, 2.x included.

Check the install:

```bash
gamut --version
python -c "import gamut; print(gamut.__version__, gamut.FORMAT)"
```

### xarray and the netCDF tools

The files are netCDF-4, so xarray and the netCDF tools read them without
this package. xarray needs a netCDF backend beside it:

```bash
pip install xarray h5netcdf h5py
```

`xr.open_dataset("polar.gamut")` gives one `row` per run, with units and
roles as attributes. Labels arrive as integer codes: code c names entry c
of the label's table, which `xr.open_dataset("polar.gamut",
group="categories")` holds.

### From a checkout

On platforms without a wheel, or to build the core yourself:

```bash
git clone https://github.com/bijective-systems-org/gamut.git
cd gamut
pip install .
```

This builds the core, so it needs a C++17 compiler and HDF5 1.14 or later
(pip fetches CMake if yours is older than 3.20). HDF5 can come from conda,
Homebrew or your system's packages; point CMake at it with
`CMAKE_ARGS="-DHDF5_ROOT=/path/to/hdf5"`. To build the core with its own
HDF5 linked in, as the wheels are:

```bash
bash tools/build_deps.sh deps                     # zlib and HDF5, static, in ./deps
CMAKE_ARGS="-DGAMUT_STATIC_HDF5=ON -DHDF5_ROOT=$PWD/deps -DZLIB_ROOT=$PWD/deps" pip install .
```

## MATLAB

Download `Gamut.mltbx` from the
[latest release](https://github.com/bijective-systems-org/gamut/releases/latest/download/Gamut.mltbx)
and open it in MATLAB, or run `matlab.addons.install('Gamut.mltbx')`. It
needs MATLAB R2023b or later on Linux, Windows or an Apple silicon Mac, and
no compiler: it carries the library, with its own HDF5 linked in apart from
MATLAB's. `matlab.addons.uninstall('Gamut')` removes it.

To read a file only, MATLAB needs nothing installed: its own `ncread`
reads every array ([reading without the package](guide/12-matlab.md#reading-without-the-package)).

### From a checkout

For an earlier MATLAB or an Intel Mac, compile the gateway yourself. The
package is the `matlab` folder of a checkout, and its gateway is compiled
once against a core library with HDF5 linked in: a release's
`gamut-core-<version>-<platform>` archive, or the Python wheel's, found
with

```bash
python -c "import gamut; print(gamut.library_path())"
```

and in MATLAB, from the checkout:

```matlab
cd matlab
build_mex('/path/printed/above')   % or build_mex alone, for a core in ../build
addpath(pwd)                       % savepath keeps it for later sessions
s = gamut.open('cylinder.gamut');   % written by examples/02_one_mesh.py
s.rowCount()
```

`build_mex` needs a C++ compiler MATLAB accepts (`mex -setup C++`; on
macOS, Xcode). It copies the core beside the gateway, so the `matlab`
folder is all MATLAB needs on its path.

## Julia

Julia 1.9 or later. Add the package from this repository, at the release
that matches the wheel's core, and point it at a core library:

```julia
using Pkg
Pkg.add(url="https://github.com/bijective-systems-org/gamut", subdir="julia", rev="v1.3.0")
ENV["GAMUT_LIBRARY"] = "/path/to/libgamut.dylib"   # .so on Linux, gamut.dll on Windows
using Gamut
Gamut.version()
```

The core is in each release's `gamut-core-<version>-<platform>` archive
(`lib/`, or `bin/` on Windows), and the Python wheel's serves too: set
`GAMUT_LIBRARY` to its path (`gamut.library_path()` prints the wheel's), in
the environment or in `ENV` before the first call. From a checkout, `julia --project=julia` uses the package in
place, and without `GAMUT_LIBRARY` it looks in `build/` at the top of the
checkout.

## C++ and C

With CMake 3.16 or later, a C++17 compiler and HDF5 1.14 or later:

```bash
cmake -S . -B build -DHDF5_ROOT=/path/to/hdf5
cmake --build build
cmake --install build --prefix /usr/local
```

This installs the library, the C++ header `include/gamut/gamut.hpp` (C++17)
and the C header `include/gamut/gamut.h` beside it, and a CMake package:

```cmake
find_package(gamut 1.0 REQUIRED)
target_link_libraries(my_tool PRIVATE gamut::gamut)
```

On Linux, a core linked to a shared HDF5 can bind to another copy of HDF5
in the same process (h5py's, MATLAB's, a solver's) and crash. If your
program may load one, link HDF5 into the library with
`-DGAMUT_STATIC_HDF5=ON` and `tools/build_deps.sh`, as above; the Python
wheels are built that way.

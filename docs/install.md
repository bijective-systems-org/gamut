# Installing

Every language uses the same core library, written in C++. The Python
wheels include it, with HDF5 linked inside, so it never meets another HDF5
in the same process: h5py's, MATLAB's or a solver's. MATLAB and Julia can
use the wheel's copy; C and C++ programs build the core from source.

## Python

```bash
pip install gamut-format                 # Python 3.10 or later
pip install "gamut-format[units]"        # with unit conversion on reads and writes (pint)
pip install "gamut-format[vtk]"          # with VTK import and export (pyvista, pandas)
```

Wheels are built for macOS (arm64 and x86_64, macOS 11 and later), Linux
(x86_64, glibc 2.28 and later) and Windows (x86_64). One wheel serves every Python version on its
platform. The only required dependency is NumPy.

Check the install:

```bash
gamut --version
python -c "import gamut; print(gamut.__version__, gamut.FORMAT)"
```

### From a checkout

Until the first release is on PyPI, and on platforms without a wheel:

```bash
git clone https://github.com/bijective-systems-org/gamut.git
cd gamut
pip install .
```

This builds the core, so it needs a C++17 compiler and HDF5 1.12 or later
(pip fetches CMake if yours is older than 3.20). HDF5 can come from conda,
Homebrew or your system's packages; point CMake at it with
`CMAKE_ARGS="-DHDF5_ROOT=/path/to/hdf5"`. To build the core with its own
HDF5 linked in, as the wheels are:

```bash
bash tools/build_deps.sh deps                     # zlib and HDF5, static, in ./deps
CMAKE_ARGS="-DGAMUT_STATIC_HDF5=ON -DHDF5_ROOT=$PWD/deps -DZLIB_ROOT=$PWD/deps" pip install .
```

## MATLAB

The MATLAB package is the `matlab` folder of a checkout. Its gateway is
compiled once against a core library; the simplest one to use is the
Python wheel's, which keeps its HDF5 apart from MATLAB's. Find it with

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

`build_mex` needs a C++ compiler MATLAB accepts (`mex -setup C++`). It
copies the core beside the gateway, so the `matlab` folder is all MATLAB
needs on its path. Tested with MATLAB R2026a on macOS, and with the
latest release on Linux.

## Julia

Julia 1.9 or later. Add the package from this repository, and point it at
a core library:

```julia
using Pkg
Pkg.add(url="https://github.com/bijective-systems-org/gamut", subdir="julia")
ENV["GAMUT_LIBRARY"] = "/path/to/libgamut.dylib"   # .so on Linux, gamut.dll on Windows
using Gamut
Gamut.version()
```

As for MATLAB, the Python wheel's core serves: set `GAMUT_LIBRARY` to the
path `gamut.library_path()` prints, in the environment or in `ENV` before
the first call. From a checkout, `julia --project=julia` uses the package in
place, and without `GAMUT_LIBRARY` it looks in `build/` at the top of the
checkout.

## C and C++

With CMake 3.16 or later, a C++17 compiler and HDF5 1.12 or later:

```bash
cmake -S . -B build -DHDF5_ROOT=/path/to/hdf5
cmake --build build
cmake --install build --prefix /usr/local
```

This installs `include/gamut/gamut.h`, the library and a CMake package:

```cmake
find_package(gamut 1.0 REQUIRED)
target_link_libraries(my_tool PRIVATE gamut::gamut)
```

On Linux, a core linked to a shared HDF5 can bind to another copy of HDF5
in the same process (h5py's, MATLAB's, a solver's) and crash. If your
program may load one, link HDF5 into the library with
`-DGAMUT_STATIC_HDF5=ON` and `tools/build_deps.sh`, as above; the Python
wheels are built that way.

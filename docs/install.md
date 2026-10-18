# Installing

Every language uses the same core library, written in C++. The Python
wheels include it, with HDF5 linked inside, so it never meets another HDF5
in the same process: h5py's, MATLAB's or a solver's. MATLAB and Julia can
use the wheel's copy; C and C++ programs build the core from source.

## Python

```bash
pip install mestra                 # Python 3.10 or later
pip install "mestra[units]"        # with unit conversion on reads and writes (pint)
pip install "mestra[vtk]"          # with VTK import and export (pyvista, pandas)
```

Wheels are built for macOS (arm64 and x86_64, macOS 11 and later), Linux
(x86_64, glibc 2.28 and later) and Windows (x86_64). One wheel serves every Python version on its
platform. The only required dependency is NumPy.

Check the install:

```bash
mestra --version
python -c "import mestra; print(mestra.__version__, mestra.FORMAT)"
```

### From a checkout

Until the first release is on PyPI, and on platforms without a wheel:

```bash
git clone https://github.com/bijective-systems-org/mestra.git
cd mestra
pip install .
```

This builds the core, so it needs a C++17 compiler and HDF5 1.12 or later
(pip fetches CMake if yours is older than 3.20). HDF5 can come from conda,
Homebrew or your system's packages; point CMake at it with
`CMAKE_ARGS="-DHDF5_ROOT=/path/to/hdf5"`. To build the core with its own
HDF5 linked in, as the wheels are:

```bash
bash tools/build_deps.sh deps                     # zlib and HDF5, static, in ./deps
CMAKE_ARGS="-DMESTRA_STATIC_HDF5=ON -DHDF5_ROOT=$PWD/deps -DZLIB_ROOT=$PWD/deps" pip install .
```

## MATLAB

The MATLAB package is the `matlab` folder of a checkout. Its gateway is
compiled once against a core library; the simplest one to use is the
Python wheel's, which keeps its HDF5 apart from MATLAB's. Find it with

```bash
python -c "import mestra; print(mestra.library_path())"
```

and in MATLAB, from the checkout:

```matlab
cd matlab
build_mex('/path/printed/above')   % or build_mex alone, for a core in ../build
addpath(pwd)                       % savepath keeps it for later sessions
s = mestra.open('cylinder.mes');   % written by examples/02_one_mesh.py
s.rowCount()
```

`build_mex` needs a C++ compiler MATLAB accepts (`mex -setup C++`). It
copies the core beside the gateway, so the `matlab` folder is all MATLAB
needs on its path. Tested with MATLAB R2026a on macOS.

## Julia

Julia 1.9 or later. The package is in `julia/`, and needs the core library:

```bash
export MESTRA_LIBRARY=/path/to/libmestra.so      # .dylib on macOS, mestra.dll on Windows
julia --project=julia -e 'using Mestra; println(Mestra.version())'
```

Without `MESTRA_LIBRARY`, it looks in `build/` at the top of the checkout.
As for MATLAB, the Python wheel's core serves: set `MESTRA_LIBRARY` to the
path `mestra.library_path()` prints.

## C and C++

With CMake 3.16 or later, a C++17 compiler and HDF5 1.12 or later:

```bash
cmake -S . -B build -DHDF5_ROOT=/path/to/hdf5
cmake --build build
cmake --install build --prefix /usr/local
```

This installs `include/mestra/mestra.h`, the library and a CMake package:

```cmake
find_package(mestra 1.0 REQUIRED)
target_link_libraries(my_tool PRIVATE mestra::mestra)
```

Add `-DMESTRA_STATIC_HDF5=ON` (with `tools/build_deps.sh` as above) to link
HDF5 into the library.

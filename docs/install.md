# Installing

Gamut is published by Bijective Systems as
[`gamut-format` on PyPI](https://pypi.org/project/gamut-format/):
install `gamut-format`, then `import gamut`; the command line is `gamut`.
The PyPI project named `gamut` is a different package.

Every language uses the same core library, written in C++. The Python
wheels and the MATLAB toolbox carry it with HDF5 linked inside, so it
never meets another HDF5 in the same process: h5py's, MATLAB's or a
solver's. The oldest versions Gamut 2 supports are Python 3.11, NumPy
1.26, MATLAB R2023b and Julia 1.10. Each is tested, and none of them
rises within 2.x.

/// tab | Python

```bash
pip install gamut-format                 # Python 3.11 or later
pip install "gamut-format[units]"        # with unit conversion on reads and writes (pint)
pip install "gamut-format[vtk]"          # with VTK import and export (pyvista, pandas)
```

Wheels are built for macOS (arm64 and x86_64, macOS 11 and later), Linux
(x86_64, glibc 2.28 and later) and Windows (x86_64). One wheel serves
every Python version on its platform. The only required dependency is
NumPy, 1.26 or later, 2.x included. To check the install:

```bash
gamut --version
python -c "import gamut; print(gamut.__version__, gamut.FORMAT)"
```

**xarray and the netCDF tools.** The files are netCDF-4, so xarray and
the netCDF tools read them without this package. xarray needs a netCDF
backend beside it, `pip install xarray h5netcdf h5py`.
`xr.open_dataset("polar.gamut")` gives one `row` per run, with units and
roles as attributes. Labels arrive as integer codes: code c names entry c
of the label's table, which `xr.open_dataset("polar.gamut",
group="categories")` holds.

**From a checkout.** On platforms without a wheel, or to build the core
yourself:

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

///

/// tab | MATLAB

Download
[`Gamut.mltbx`](https://github.com/bijective-systems-org/gamut/releases/latest/download/Gamut.mltbx)
from the latest release and open it in MATLAB, or install it with

```matlab
matlab.addons.install('Gamut.mltbx')
```

It needs MATLAB R2023b or later on Linux, Windows or an Apple silicon Mac,
and no compiler: it carries the library, with its own HDF5 linked in apart
from MATLAB's. `matlab.addons.uninstall('Gamut')` removes it.

To read a file only, MATLAB needs nothing installed: its own `ncread`
reads every array ([reading without the package](reference/matlab.md#reading-without-the-package)).

**Compiling the gateway.** For an earlier MATLAB or an Intel Mac, compile
the gateway yourself. The package is the `matlab` folder of a checkout,
and its gateway is compiled once against a core library with HDF5 linked
in: a release's `gamut-core-<version>-<platform>` archive, or the Python
wheel's, which `python -c "import gamut; print(gamut.library_path())"`
prints. Then, in MATLAB, from the checkout:

```matlab
cd matlab
build_mex('/path/printed/above')   % or build_mex alone, for a core in ../build
addpath(pwd)                       % savepath keeps it for later sessions
```

`build_mex` needs a C++ compiler MATLAB accepts (`mex -setup C++`; on
macOS, Xcode). It copies the core beside the gateway, so the `matlab`
folder is all MATLAB needs on its path.

///

/// tab | Julia

Julia 1.10 or later. Add the package from this repository, at the release
that matches the core it calls, and point it at a core library:

```julia
using Pkg
Pkg.add(url="https://github.com/bijective-systems-org/gamut", subdir="julia", rev="v2.0.0")
ENV["GAMUT_LIBRARY"] = "/path/to/libgamut.dylib"   # .so on Linux, gamut.dll on Windows
using Gamut
Gamut.version()
```

The core is in each release's `gamut-core-<version>-<platform>` archive
(`lib/`, or `bin/` on Windows), and the Python wheel's serves too:
`gamut.library_path()` prints its path. Set `GAMUT_LIBRARY` in the
environment, or in `ENV` before the first call; `Gamut.version()` says
which core was loaded. From a checkout, `julia --project=julia` uses the
package in place, and without `GAMUT_LIBRARY` it looks in `build/` at the
top of the checkout.

///

/// tab | C++

The core builds with CMake 3.16 or later, a C++17 compiler and HDF5 1.14
or later:

```bash
cmake -S . -B build -DHDF5_ROOT=/path/to/hdf5
cmake --build build
cmake --install build --prefix /usr/local
```

Installing it puts the library, the C++ header `include/gamut/gamut.hpp`
(C++17), the C header `include/gamut/gamut.h` and a CMake package in the
prefix, which accepts any 2.x core:

```cmake
find_package(gamut 2.0 REQUIRED)
target_link_libraries(my_tool PRIVATE gamut::gamut)
```

On Linux, a core linked to a shared HDF5 can bind to another copy of HDF5
in the same process (h5py's, MATLAB's, a solver's) and crash. If your
program may load one, link HDF5 into the library with
`bash tools/build_deps.sh deps`, then configure with
`-DGAMUT_STATIC_HDF5=ON -DHDF5_ROOT=$PWD/deps -DZLIB_ROOT=$PWD/deps`; the
Python wheels are built that way.

///

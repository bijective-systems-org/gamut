# One core, every language

Every language reads and writes through the same library: a core written
in C++ that implements the format, writing, reading, selecting rows,
validating and the built-in model, behind a C interface,
[`gamut.h`](https://github.com/bijective-systems-org/gamut/blob/main/include/gamut/gamut.h),
which is all the library exports. Each language is a thin layer over that
interface, C++ included:

![Python (with the command line), MATLAB, Julia, C++ and C each read and write a .gamut file through the C interface of the one C++ core; Rust and Fortran are planned.](../assets/languages.svg#only-light)
![Python (with the command line), MATLAB, Julia, C++ and C each read and write a .gamut file through the C interface of the one C++ core; Rust and Fortran are planned.](../assets/languages-dark.svg#only-dark)

| Language | Reaches the core through | Installed as |
|---|---|---|
| Python | `ctypes` | the `gamut-format` wheel, core included |
| MATLAB | a MEX gateway | the `Gamut.mltbx` toolbox, core included |
| Julia | `ccall` | the package, pointed at a release's core or the wheel's |
| C++ | [`gamut.hpp`](https://github.com/bijective-systems-org/gamut/blob/main/include/gamut/gamut.hpp), a header over `gamut.h` | the core built with CMake |
| C | `gamut.h` | the core built with CMake |
| Command line | the Python package | `gamut` and `gamut-vtk`, installed with the wheel |

## What that means

A file written in one language is read the same in every other, value for
value, because one library reads it. A refusal is the same everywhere: the
core decides it, and every language reports the rule it names (`E7` for
units that do not parse), as `GamutError.rule` in Python and Julia, the
error identifier `gamut:E7` in MATLAB, `gamut::Error::rule()` in C++ and
the `gamut_error` filled by every C call. A condition passed to `select`
means the same in every language, and the built-in model gives the same
answers to the last bit.

The packages carry the core with HDF5 linked inside it, so it never meets
another copy of HDF5 in the same process: h5py's, MATLAB's or a solver's.

## What differs

Each language spells the calls its own way, and counts positions its own
way: from 0 in Python, C++ and C, from 1 in MATLAB and Julia. The codes
stored for a label or mesh label count from 0 in every language, since
they are part of the file. The [reference](../reference/matlab.md) gives
each language's spelling of the same calls.

Some conveniences live in one language. Python converts units on reads
and writes (through pint), takes and gives pandas tables, imports and
exports VTK, and provides the `gamut` command line. Model types of your
own are registered in Python or MATLAB; Julia, C++ and C evaluate the
built-in model.

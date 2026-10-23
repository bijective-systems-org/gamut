# Contributing

The [specification](SPEC.md) and the [corpus](corpus) define Gamut. The
C++ core in `src/` implements them once; Python, MATLAB, Julia and the C++
header are thin layers over its C interface. A change of behaviour starts from the
specification and the corpus, never from one language.

## A bug

Describe what happened and what you expected, with the smallest file or
script that shows it, and the output of `gamut --version`. A fix comes
with a test at the layer that owns the problem: the core's tests for the
core, the language's tests for its layer, the corpus for anything every
language must agree on.

## A change to the format

Open an issue first, with:

1. a real study or workflow that the format cannot hold today;
2. the meaning proposed, and what readers that do not know it will do;
3. whether it is an addition within version 1 (SPEC.md section 17: a
   reader that does not know it reports W5 and goes on) or needs a new
   major version;
4. the corpus cases that pin it.

The specification, the corpus and the core change together.

## Building and running the checks

The core needs CMake 3.16 or later, a C++17 compiler and HDF5 1.12 or
later (or `tools/build_deps.sh` and `-DGAMUT_STATIC_HDF5=ON`, as in
[installing](docs/install.md)). From the top of a checkout:

```bash
cmake -S . -B build -DHDF5_ROOT=/path/to/hdf5
cmake --build build -j2
./build/core_unit_tests && ./build/core_writer_reader_tests
(cd build && ./header_tests)
```

Python finds the core in `build/` when run from the checkout:

```bash
pip install numpy pytest h5py pint xarray netCDF4 pyvista pandas
cd python && python -m pytest -q tests
```

The tests also run every script in `examples/`, check that each page of
`docs/guide/` quotes its example and shows what it prints, run the
command-line page's sessions, and build the C example. Change an example
and its page together.

Julia's tests, and the corpus from Python and Julia (the Julia check needs
the JSON package in its environment):

```bash
julia --project=julia -e 'include("julia/test/runtests.jl")'
python corpus/generate.py /tmp/corpus
GAMUT_LIBRARY=build/libgamut.so python corpus/check.py /tmp/corpus
julia --project=<an environment with JSON and Gamut> julia/test/check_corpus.jl /tmp/corpus
```

In MATLAB, from `matlab/`: `build_mex`, then `run_tests`, then
`corpus='/tmp/corpus'; run('tests/check_corpus.m')`.
`package_toolbox('Gamut.mltbx')` packages the gateways built there as the
toolbox, and `tests/check_toolbox.m` installs it in a clean session and
runs an example with it. `bash tools/build_core.sh PREFIX DEPS` installs
the core as a release carries it, with its headers, CMake package and
licences.

`tools/damaged_files.py` measures how readers meet damaged files, and
`bench/` holds the benchmarks (`bench/figures.py` rebuilds the benchmark
page's tables and figures from `bench/results/`).

## Style

Code reads like the code around it: plain names, few comments, each
saying why. Messages say what is wrong and what to do, with the rule
(`E7`) when one applies. Documentation is short and tested where it can
be.

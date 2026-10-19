# Reading map

For an engineer or agent opening Gamut cold. It points into the documents
that own each subject and repeats none of them.

## What Gamut is

An open file format, HDF5 laid out as valid netCDF-4, for the results of a
parametric simulation study and the models fitted to it; one C++ core that
implements it, with a C interface; Python, MATLAB, Julia and C++ layers
over that interface; a validator; a command line; VTK conversion.

## Where things are

| Path | Holds |
|---|---|
| `SPEC.md` | the format: meaning, layout, validation rules (E1-E24, W1-W10), versions |
| `corpus/` | valid, rule-breaking and hostile files (`generate.py`) and their expected outcomes, checked from every language (`check.py`, `julia/test/check_corpus.jl`, `matlab/tests/check_corpus.m`) |
| `include/gamut/gamut.h` | the C interface, the only surface any language uses |
| `include/gamut/gamut.hpp` | the C++ layer, header-only over `gamut.h`; tested by `tests/header_tests.cpp` against the shared library |
| `src/` | the core: writer, reader, validator, selector, copies, units grammar |
| `tests/` | the core's C++ tests; `two_hdf5_linux.sh`, two HDF5 copies in one process |
| `python/gamut/` | the Python layer (ctypes), the command line (`cli.py`), VTK conversion (`vtk.py`) |
| `matlab/`, `julia/` | the MATLAB and Julia layers and their tests |
| `examples/` | runnable examples; each guide page quotes one, and the README quotes `00_readme.py` and the MATLAB, Julia and C++ examples |
| `docs/` | install, the guide, reference, security, comparison, benchmarks |
| `bench/` | benchmark scripts and results; `bench/figures.py` writes the page's tables and figures |
| `tools/` | `build_deps.sh` (static zlib and HDF5), `damaged_files.py` |

## Who owns what

| Subject | Authority |
|---|---|
| What a file means, what is valid | `SPEC.md` |
| The expected outcome of a case, in every language | the corpus |
| Behaviour | the core; a language layer converts types and positions, nothing more |
| Names and argument order across languages | the guide pages 12-14 and each layer's docstrings, which follow the Python names |
| Which rows train a model, how a model computes, file lineage | the producing or consuming tool, never Gamut |

## Boundaries worth knowing before an edit

- **One implementation.** A rule lives in the core. A language layer that
  checks or computes something the core should is a defect.
- **Namespaces.** The core's own C++ in `src/` is `gamut_core`; the
  public C++ header owns `gamut`. They meet only through the C interface,
  and the shared library exports only `gamut_*`.
- **Models hold no code.** A model's numbers are plain data; the software
  that owns a model type registers it (Python and MATLAB; Julia evaluates
  the built-in nearest model only). An unregistered type opens and reads;
  evaluating it is refused with the type's name.
- **Correspondence is the producer's claim.** A shared mesh says node k is
  the same point in every run; the file cannot check physical meaning.
- **Untrusted files.** Counts are checked against stated limits before
  buffers are sized; links are never followed; the packaged core loads no
  HDF5 plugins. HDF5 itself can hang on a damaged file: the defence is a
  process boundary (`docs/security.md`).
- **HDF5 linked in.** Packages link HDF5 statically and export only the
  `gamut_*` symbols: on Linux a core linked to a shared HDF5 crashes beside a
  second HDF5 in the process (h5py's, MATLAB's).
- **Versions.** The package version (`1.0.0`) is not the format version
  (`gamut/1`); a reader refuses another major format version.
- **Documentation is tested.** Guide and README code blocks are lines of the
  examples and output blocks what they print; benchmark numbers come from
  `bench/results/`.

## Build and test

[CONTRIBUTING.md](CONTRIBUTING.md) lists every check as CI runs it.

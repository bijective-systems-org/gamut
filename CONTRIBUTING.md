# Contributing

The specification and conformance corpus define Mestra. Repository
maintainers review changes to that contract; no language implementation
has authority to redefine it by changing behavior alone.

For a bug fix, describe the observed failure, provide a small reproducer
and test the intended behavior at the affected interface. Keep changes
local to the layer that owns the problem. Model-training policy,
producer lineage and application transactions ordinarily belong in the
consumer or producer, using the existing schema.

For a format change, open an issue or proposal containing:

1. A concrete file/workflow that the current format cannot represent.
2. The proposed semantics and the behavior of existing readers.
3. A compatibility decision under SPEC section 28.
4. Corpus additions and the changes required in each implementation.

Within `mestra/0`, optional attributes/groups can be added under the
existing unknown-content rules. A new role, statistic, cell type,
`source` keyword or required attribute is not additive. Existing meaning
cannot change within version 0. Incompatible changes require a major
format version; Python package versions are separate from that version.

Update the spec, corpus and affected implementations together. An
implementation-specific limitation must be exposed in
[compatibility.md](docs/compatibility.md). Use structural equality
across languages/HDF5 versions; require deterministic bytes only where
SPEC section 30 does. Run the relevant tests locally and the full CI
matrix before release. [releasing.md](docs/releasing.md) lists the gates.

## Running the checks

From the repository root, as `.github/workflows/ci.yml` runs them:

    python vectors/generate.py --on-demand   # once: three files too big to commit
    python vectors/check.py                  # needs h5py, numpy, netCDF4, h5netcdf

    pip install -e "python/[dev]"
    (cd python && python -m pytest -q && python -m ruff check . && python -m mypy)

    cmake -S cpp -B cpp/build -DHDF5_ROOT=<hdf5 prefix> \
          -DPython3_EXECUTABLE=<a python with h5py>
    cmake --build cpp/build
    ctest --test-dir cpp/build --output-on-failure

    julia --project=julia -e 'using Pkg; Pkg.instantiate(); Pkg.test()'

    matlab -batch "addpath('matlab'); run('matlab/tests/run_tests.m')"

Each language's README says more about its own setup;
[cpp/README.md](cpp/README.md) explains `HDF5_ROOT`.

The current callable envelope is intentionally small. A new tool can
register its own callable type without making the model's internals
part of Mestra. Readers that do not own that type preserve its dictionary
and public interface, and refuse unsupported execution explicitly.

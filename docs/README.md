# Gamut documentation

Gamut, by [Bijective Systems](https://github.com/bijective-systems-org), is
an open file format for parametric simulation studies and the models
fitted to them. A `.gamut` file is HDF5 laid out as valid netCDF-4, with
libraries for Python, MATLAB, Julia, C++ and C.

The Python distribution on [PyPI](https://pypi.org/project/gamut-format/)
is **gamut-format**: install `gamut-format`, then `import gamut`.
The command line is `gamut`. The PyPI project named `gamut` is a different
package. [Installing](install.md) covers each language and platform.

## Start with a study

- [Overview and examples](../README.md): write, append and read a study in four languages.
- [Guide](guide/README.md): one concept per page, quoting runnable programs in [examples](../examples).
- [Run tables](guide/01-run-tables.md): inputs, status and results with units.
- [Shared meshes](guide/02-one-mesh.md): fields as runs by nodes or cells.
- [Fitted models](guide/07-models.md): store a model's numbers and evaluate new inputs.
- [Command line](guide/11-command-line.md): inspect, validate, build and extract files.

## Reference and interoperability

- [File format specification](../SPEC.md): the authoritative layout, meaning, validation rules and format versions.
- [Selecting rows](reference/selecting.md): the query grammar.
- [C API](../include/gamut/gamut.h) and [C++ API](../include/gamut/gamut.hpp): public headers.
- [Python API](../python/gamut/__init__.py): public functions and docstrings, also available through `help(gamut)`.
- [Conformance corpus](../corpus): valid, invalid and hostile files with expected outcomes.
- [Files from outside](security.md): validation and process boundaries for untrusted files.
- [Comparison](comparison.md) and [benchmarks](benchmarks.md): scope, trade-offs and measured workloads.

The package version and file format version are separate: a file declares
`gamut/1`. [The specification's version rules](../SPEC.md#17-versions-and-additions)
define compatibility. [Release history](../CHANGELOG.md) describes package changes.

## Plain-text entry points

[llms.txt](https://raw.githubusercontent.com/bijective-systems-org/gamut/main/llms.txt)
collects API patterns and raw documentation links for coding agents.
The [raw specification](https://raw.githubusercontent.com/bijective-systems-org/gamut/main/SPEC.md)
defines the format; the [citation metadata](../CITATION.cff) identifies the software.
The canonical source and documentation live in the
[Gamut repository](https://github.com/bijective-systems-org/gamut).
